from typing import Optional, List, Dict, Tuple, Iterable, AsyncIterator
from enum import Enum
from abc import ABC, abstractmethod
import logging
import re
import asyncio
from .utils import Message, OrientedGraphNode, PeekableQueue, OneTimeEvent
from .thoughts import Thought, collect_branch, EOS_THOUGHT
from .model import LLM

logger = logging.getLogger(__name__)

class Status(Enum):
    IDLE = 0
    RUNNING = 1
    FINISHED = 2
    ASLEEP = 3

class Operation(ABC, OrientedGraphNode):
    """
    Node of Graph of Operations

    Attributes:
        id (int):                   Unique operation identifier
        parents (List[Operation]):  List of parent operations
        status (Status):            Status of operation in execution
        name (str):                 Name of operation
        description (str):          Description of operation
        tags (Dict[str, any]):      Dictionary of custom tags
        thoughts (List[Thought]):   List of created thoughts
        finished (OneTimeEvent):    One-time-event signaling completion of operation
        subscribers (List[PeekableQueue]):
                                    List of queues for sending thoughts to child operations
        subscribtions (Dict[Operation, PeekableQueue]):
                                    Dictionary of queues to read thought from corresponding to parent operations
    """
    id_counter: int = 0
    DEFAULT_NAME = "Operation"

    def __init__(
            self,
            parents: Optional[Iterable]=None,
            children: Optional[Iterable]=None,
            status: Status=Status.IDLE,
            name: Optional[str]=None,
            description: str="",
            tags: Optional[Dict[str, any]]=None
            ):
        self.finished = OneTimeEvent()
        self.subscribers: List[PeekableQueue] = []
        self.subscribtions: Dict[Operation, PeekableQueue] = {}
        super().__init__(parents, children)
        self.status = status
        self._init_status = status
        self.name = name if name else self.DEFAULT_NAME + f" {self.id}"
        self.description = description
        self.tags = tags if tags else {}
        self.thoughts: List[Thought] = []
    
    def __hash__(self):
        return self.id

    def add_children(self, children):
        OrientedGraphNode.add_children(self, children)
        for child in children:
            queue = PeekableQueue()
            self.subscribers.append(queue)
            child.subscribtions[self] = queue

    def add_parents(self, parents):
        OrientedGraphNode.add_parents(self, parents)
        for parent in parents:
            queue = PeekableQueue()
            self.subscribtions[parent] = queue
            parent.subscribers.append(queue)

    # default condition
    async def check_condition(self) -> bool:
        return True

    @abstractmethod
    async def operation(self) -> None:
        pass

    async def run(self, **kwargs) -> None:
        if (not await self.check_condition()):
            logger.info(f"[{self.name}] start condition has not been met")
            self.status = Status.IDLE
            for queue in self.subscribtions.values():
                queue.clear()
            return
        tasks = []
        for child in self.children:
            if child.status is not Status.RUNNING:
                child.status = Status.RUNNING
                tasks.append(asyncio.create_task(child.run(**kwargs)))
        
        logger.info(f"[{self.name}] started")
        await self.operation()
        logger.info(f"[{self.name}] finished with {len(self.thoughts)} thoughts generated")

        for subscriber in self.subscribers:
            #TODO: process query waiting
            subscriber.put_nowait(EOS_THOUGHT)

        self.status = Status.FINISHED
        self.finished.set()
        #TODO: process exceptions
        #TODO: perhaps, return tasks instead, and await them on the top level?
        logger.info(f"[{self.name}] awaiting {len(tasks)} other operations to finish")
        if tasks:
            await asyncio.gather(*tasks) # , return_exceptions=True
        logger.info(f"[{self.name}] exiting")
    
    def clear(self, propogate=True):
        self.thoughts: List[Thought] = []
        for queue in self.subscribers:
            queue.clear()
        self.status = self._init_status

        if propogate:
            for child in self.children:
                child.clear()

    #TODO: correct copy for specific operations
    def copy(self, *args, **kwargs):
        op_copy = super().copy(
            *args,
            status=self.status,
            name=self.name,
            description=self.description,
            tags=self.tags.copy(),
            **kwargs
        )
        return op_copy


class BasicOperation(Operation):
    DEFAULT_NAME = "BasicOperation"

    @abstractmethod
    async def thought_collector(self) -> AsyncIterator[Tuple[Iterable[Thought], any]]:
        pass

    @abstractmethod
    async def operation_task(self, thoughts: Iterable[Thought], **kwargs) -> List[Thought]:
        pass

    async def operation(self):
        thought_collector = self.thought_collector()
        tasks = []
        async for thoughts, kwargs in thought_collector:
            task = asyncio.create_task(self.operation_task(thoughts, **kwargs))
            task.add_done_callback(self._handle_thoughts)
            tasks.append(task)
        await asyncio.gather(*tasks)

    def _handle_thoughts(self, task):
        try:
            thoughts = task.result()
            self.thoughts += thoughts
            for thought in thoughts:
                for subscriber in self.subscribers:
                    #TODO: process query waiting
                    subscriber.put_nowait(thought)
        except Exception as e:
            logger.error(f"[{self.name}] Error while processing operation_task result in _handle_thoughts: {e}")


class Generator(BasicOperation):
    DEFAULT_NAME = "Generator"

    def __init__(
            self,
            model: LLM,
            generation_config: Optional[Dict]=None,
            **kwargs
            ):
        super().__init__(
            **kwargs
            )
        self.model = model
        self.generation_config = generation_config
    
    @abstractmethod
    async def make_prompt(self, **kwargs) -> List[Message]:
        pass

    # default parser
    def parse_generation(self, text: str) -> List[str]:
        return [text]

    async def operation_task(self, parents, **kwargs):
        messages = self.make_prompt(**kwargs)
        response = await self.model.generate(messages, self.generation_config)
        if response is None:
            logger.error(f"[{self.name}] generation unsuccesfull!")
            return
        logger.info(f"[{self.name}] generation succesfull (generated strlen: {len(response)})")
        responses = self.parse_generation(response)
        thoughts = []
        for response in responses:
            thought = Thought(response, parents=parents, prompt=messages)
            thoughts.append(thought)
        return thoughts


async def parents_finished(parents: List[Operation]) -> bool:
    for parent in parents:
        if parent.status is not Status.FINISHED:
            await parent.finished.wait()
    return True

async def recieved_any_thought(subscribtions: Dict[Operation, PeekableQueue], parents: List[Operation]):
    tasks = []
    for parent in parents:
        if parent.status is Status.ASLEEP:
            continue
        tasks.append(asyncio.create_task(subscribtions[parent].peek()))
    while tasks:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        tasks = list(pending)
        t_flag = False
        for task in done:
            try:
                thought = task.result()
                if "EOS" not in thought.tags.keys():
                    t_flag = True
                    for pending_task in pending:
                        pending_task.cancel()
            except Exception as e:
                logger.error(f"Error while processing thought in recieved_any_thought: {e}")
        if t_flag:
            return True
    return False

class SimplePromptGenerator(Generator):
    DEFAULT_NAME = "SimplePromptGenerator"

    def __init__(
            self,
            model: LLM,
            messages: List[Message],
            **kwargs
            ):
        super().__init__(
            model=model,
            **kwargs
            )
        self.messages = messages
    
    async def thought_collector(self):
        yield ([], {})

    def make_prompt(self, **kwargs):
        return self.messages
    
    async def run(self, **kwargs):
        replace = kwargs.get("replace", {})
        for src, dst in replace.items():
            for message in self.messages:
                message["content"] = message["content"].replace(src, dst)
        await super().run(**kwargs)


#TODO: error processing
async def one_thought_waiter(subscribtions: Dict[Operation, PeekableQueue], operation: Operation) -> AsyncIterator[Thought]:
    queue = subscribtions[operation]
    while queue.empty():
        thought = await asyncio.create_task(queue.get())
        if "EOS" in thought.tags.keys():
            break
        yield thought

#TODO: error processing
async def all_thoughts_waiter(subscribtions: Dict[Operation, PeekableQueue], operation: Operation) -> List[Thought]:
    if operation.status is Status.ASLEEP:
        return []
    elif operation.status is not Status.FINISHED:
        await operation.finished.wait()
    queue = subscribtions[operation]
    thoughts = []
    while not queue.empty():
        thought = queue.get_nowait()
        if "EOS" in thought.tags.keys():
            break
        thoughts.append(thought)
    return thoughts

#TODO: error processing
async def all_operations_waiter(subscribtions: Dict[Operation, PeekableQueue], operations: List[Operation]) -> List[Thought]:
    thoughts = []
    for operation in operations:
        thoughts += await all_thoughts_waiter(subscribtions, operation)
    return thoughts

async def any_thought_waiter(subscribtions: Dict[Operation, PeekableQueue], operations: List[Operation]) -> AsyncIterator[Thought]:
    tasks = {}
    for operation in operations:
        if operation.status == Status.ASLEEP \
            or operation.status == Status.FINISHED and subscribtions[operation].empty():
            continue
        queue = subscribtions[operation]
        task = asyncio.create_task(queue.get())
        tasks[task] = operation
    
    while tasks:
        done, _ = await asyncio.wait(
            tasks.keys(),
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in done:
            operation = tasks[task]
            try:
                item = task.result()
                if item:
                    if "EOS" in item.tags.keys():
                        continue
                    yield item
                new_task = asyncio.create_task(subscribtions[operation].get())
                tasks[new_task] = operation
                
            except Exception as e:
                logger.error(f"Error while trying to get operation ({operation.name}) result in any_thought_waiter: {e}")
            finally:
                del tasks[task]


class SimpleForwardGenerator(Generator):
    DEFAULT_NAME = "SimpleForwardGenerator"

    async def thought_collector(self):
        thought_generator = any_thought_waiter(self.subscribtions, self.subscribtions.keys())        
        async for thought in thought_generator:
            yield ([thought], {"text": thought.text})


class SimpleAggrigator(Generator):
    DEFAULT_NAME = "SimpleAggrigator"

    async def check_condition(self):
        return await parents_finished(self.parents)

    async def thought_collector(self):
        thoughts = await all_operations_waiter(self.subscribtions, self.parents)
        yield (thoughts, {"texts": list(map(lambda x: x.text, thoughts))})


class Tagger(BasicOperation):
    DEFAULT_NAME = "Tagger"

    def __init__(
        self,
        do_copy_thought: bool=False,
        **kwargs
        ):
        super().__init__(
            **kwargs
            )
        self.do_copy_thought = do_copy_thought
    
    @abstractmethod
    async def get_tags(self, **kwargs) -> Dict[str, any]:
        pass

    async def operation_task(self, thoughts: Iterable[Thought], **kwargs):
        tags = await self.get_tags(**kwargs)
        thought = thoughts[0]
        if self.do_copy_thought:
            parents = thoughts[1:]
            thought = Thought(thought.text, parents=parents + [thought], tags=thought.tags.copy())
        thought.tags.update(tags)
        return [thought]


class SimpleIterationCounter(Tagger):
    DEFAULT_NAME = "SimpleIterationCounter"

    def __init__(
            self,
            tag_name: str="iteration",
            **kwargs
    ):
        super().__init__(**kwargs)
        self.tag_name = tag_name

    async def thought_collector(self):
        thoughts = any_thought_waiter(self.subscribtions, self.parents)
        async for thought in thoughts:
            branch = collect_branch(thought)
            branch.reverse()
            for t in branch:
                if self.tag_name in t.tags.keys():
                    yield ([thought, thought], {"prev": t.tags[self.tag_name]})
                    break
            else:
                yield ([thought, thought], {"prev": 0})
        
    async def get_tags(self, prev) -> Dict[str, any]:
        return {"iteration": prev + 1}

class TagGenerator(Tagger):
    def __init__(
            self,
            model: LLM,
            generation_config: Optional[Dict]=None,
            **kwargs
            ):
        super().__init__(**kwargs)
        self.model = model
        self.generation_config = generation_config

    @abstractmethod
    async def make_prompt(self, **kwargs) -> List[Message]:
        pass

    @abstractmethod
    def parse_generation(text: str) -> Dict[str, any]:
        pass

    async def get_tags(self, **kwargs) -> Dict[str, any]:
        messages = self.make_prompt(**kwargs)
        response = await self.model.generate(messages, self.generation_config)
        if response is None:
            logger.error(f"[{self.name}] generation unsuccesfull!")
            return {}
        logger.info(f"[{self.name}] generation succesfull (generated strlen: {len(response)})")
        return self.parse_generation(response)


class SimpleScoreGenerator(TagGenerator):
    def __init__(
            self,
            model,
            tag_name: str="score",
            **kwargs
            ):
        super().__init__(
            model,
            **kwargs
            )
        self.tag_name = tag_name

    def parse_generation(self, text: str) -> Dict[str, float]:
        matches = re.findall(r"\\boxed{(\d+(?:\.\d+)?)}", text)
        if matches:
            return {self.tag_name: float(matches[-1])}
        else:
            logger.error(f"[{self.name}] Error while parsing generation of score")
            return {self.tag_name: 0.0}


class ChoiceDummyOperation(BasicOperation):
    DEFAULT_NAME = "ChoiceDummyOperation"

    async def check_condition(self):
        return await recieved_any_thought(self.subscribtions, self.parents)

    async def thought_collector(self):
        thoughts = any_thought_waiter(self.subscribtions, self.parents)
        async for thought in thoughts:
            yield ([thought], {})

    async def operation_task(self, thoughts: Iterable[Thought], **kwargs):
        return thoughts


class SimpleRouter(BasicOperation):
    DEFAULT_NAME = "SimpleRouter"

    def __init__(
            self,
            choices: Iterable[str],
            do_copy_thought: bool=False,
            **kwargs
            ):
        super().__init__(**kwargs)
        self.choices = {choice: ChoiceDummyOperation(parents=[self], name=self.name + f" (choice {choice})") for choice in choices}
        self.do_copy_thought = do_copy_thought
    
    @abstractmethod
    async def route(self, **kwargs) -> str:
        pass

    async def operation_task(self, thoughts, **kwargs):
        choice = await self.route(**kwargs)
        thought = thoughts[0]
        if self.do_copy_thought:
            thought = Thought(
                thought.text,
                parents=thoughts[1:] + [thought],
                tags=thought.tags.copy()
                )
        #TODO: process queue waiting
        self.choices[choice].subscribtions[self].put_nowait(thought)
        return []


#TODO: add parameter to ignore thoughts without a score
class NBestFilter(SimpleRouter):
    DEFAULT_NAME = "NBestFilter"

    def __init__(
            self,
            n_best: int,
            tag_name: str="score",
            **kwargs
            ):
        super().__init__(choices=["True", "False"], **kwargs)
        self.tag_name = tag_name
        self.n_best = n_best

    async def check_condition(self):
        self.count = 0
        return await parents_finished(self.parents)

    async def thought_collector(self):
        parents = await all_operations_waiter(self.subscribtions, self.parents)
        scored_parents = []
        unscored_parents = []
        for parent in parents:
            if self.tag_name in parent.tags.keys() \
                and type(parent.tags[self.tag_name]) == float:
                scored_parents.append((parent, parent.tags[self.tag_name]))
            else:
                #TODO: add warning
                unscored_parents.append(parent)
        scored_parents.sort(reverse=True, key=lambda x: x[1])
        n_best = min(self.n_best, len(scored_parents))
        if scored_parents:
            threshold = scored_parents[n_best - 1][1]
        for parent, score in scored_parents:
            yield ([parent], {"score": score, "threshold": threshold})
        for parent in unscored_parents:
            yield ([parent], {"score": 0.0, "threshold": 1.0})

    async def route(self, score: float, threshold: float):
        if self.count >= self.n_best:
            logger.info(f"[{self.name}] route - False (over limit)")
            return "False"
        if score >= threshold:
            self.count += 1
            logger.info(f"[{self.name}] route - True (high score: {score})")
            return "True"
        logger.info(f"[{self.name}] route - False (low score: {score})")
        return "False"
    
    def clear(self, propogate=True):
        self.count = 0
        super().clear(propogate)


# TODO: activator and waiter
# TODO: 

# TODO: rewrite as subclass of ...
class IterationFilter(SimpleRouter):
    def __init__(
            self,
            threshold: int,
            tag_name: str="iteration",
            **kwargs):
        super().__init__(choices=["Less", "GreaterOrEqual"], **kwargs)
        self.threshold = threshold
        self.tag_name = tag_name
    
    async def thought_collector(self):
        parents = any_thought_waiter(self.subscribtions, self.parents)
        async for parent in parents:
            if self.tag_name in parent.tags.keys():
                yield ([parent], {"iteration": parent.tags[self.tag_name]})
    
    async def route(self, iteration):
        logger.info(f"[{self.name}] iteration {iteration}")
        return "Less" if iteration < self.threshold else "GreaterOrEqual"
