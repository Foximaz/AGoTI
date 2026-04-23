from typing import Dict, Iterable, Optional
from collections import deque
import asyncio

type Message = Dict[str, str]

class OrientedGraphNode:
    """
    Node of oriented graph

    Attributes:
        parents (List[OrientedGraphNode]):  List of parent nodes
        children (List[OrientedGraphNode]): List of child nodes
        id (int):                           Unique node identifier
    """

    id_counter: int = 0

    def __init__(
            self,
            parents: Optional[Iterable]=None,
            children: Optional[Iterable]=None,
            id: Optional[int]=None
            ):
        if id:
            self.id = id
            if id >= self.__class__.id_counter:
                self.__class__.id_counter = id + 1
        else:
            self.id = self.__class__.id_counter
            self.__class__.id_counter += 1

        parents = parents if parents else []
        children = children if children else []
        self.parents = set()
        self.children = set()
        self.add_parents(parents)
        self.add_children(children)
    
    def add_parents(self, parents: Iterable) -> None:
        parents = set(parents)
        self.parents.update(parents)
        for parent in parents:
            parent.children.add(self)
    
    def add_children(self, children: Iterable) -> None:
        children = set(children)
        self.children.update(children)
        for child in children:
            child.parents.add(self)
    
    def clear_refs(self):
        self.parents = None
        self.children = None

    def copy(self, *args, **kwargs):
        return self.__class__(*args, parents=None, children=None, id=self.id, **kwargs)


class OrientedGraph:
    def __init__(self, nodes: Iterable[OrientedGraphNode] | Dict[int, OrientedGraphNode]):
        if type(nodes) == dict:
            self.id_to_node = nodes
        else:
            self.id_to_node = {node.id: node for node in nodes}
    
    def copy(self, *args, **kwargs):
        id_to_node_copy = {}
        for id, node in self.id_to_node.items():
            id_to_node_copy[id] = node.copy()
        
        for id, node in self.id_to_node.items():
            parents_copy = [id_to_node_copy[parent.id] for parent in self.id_to_node[id].parents]
            id_to_node_copy[id].add_parents(parents_copy)
        return self.__class__(*args, **kwargs)


class PeekableQueue:
    def __init__(self):
        self._queue = deque()
        self._get_waiter = asyncio.Condition()
    
    async def put(self, item):
        self._queue.append(item)
        async with self._get_waiter:
            self._get_waiter.notify()
    
    def put_nowait(self, item):
        self._queue.append(item)
        if self._get_waiter._waiters:
            asyncio.create_task(self._notify_waiters())
    
    async def get(self):
        while not self._queue:
            async with self._get_waiter:
                await self._get_waiter.wait()
        return self._queue.popleft()
    
    def get_nowait(self):
        if not self._queue:
            raise asyncio.QueueEmpty
        return self._queue.popleft()
    
    async def peek(self):
        while not self._queue:
            async with self._get_waiter:
                await self._get_waiter.wait()
        return self._queue[0]
    
    def peek_nowait(self):
        if not self._queue:
            raise asyncio.QueueEmpty("No items in queue")
        return self._queue[0]
    
    def empty(self) -> bool:
        return len(self._queue) == 0
    
    def qsize(self) -> int:
        return len(self._queue)
    
    async def _notify_waiters(self):
        async with self._get_waiter:
            self._get_waiter.notify()
    
    def clear(self) -> None:
        self._queue = deque()


class QueueEmpty(Exception):
    pass


class OneTimeEvent:
    def __init__(self):
        self._current_future: Optional[asyncio.Future] = None
        self._create_new_future()
    
    def _create_new_future(self):
        self._current_future = asyncio.Future()
    
    async def wait(self):
        await self._current_future
    
    def set(self):
        if not self._current_future.done():
            self._current_future.set_result(True)
        self._create_new_future()
