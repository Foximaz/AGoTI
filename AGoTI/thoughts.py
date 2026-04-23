from typing import Iterable, List, Dict, Optional, Any
from .utils import OrientedGraphNode, Message

class Thought(OrientedGraphNode):
    """
    Node of Graph Reasoning State

    Attributes:
        id (int):                Unique Thought identifier
        text (str):              Generated thought
        parents (List[Thought]): Parent Thoughts
        prompt (List[Message]):  Prompt used to generate Thought
        tags (Dict[str, Any]):   Custom tags
    """

    id_counter: int = 0

    def __init__(
            self,
            text: str,
            parents: Optional[Iterable]=None,
            prompt: Optional[List[Message]]="",
            tags: Optional[Dict[str, Any]]=None,
            id: Optional[int]=None
            ):
        super().__init__(parents, None, id) # GoT is acyclic
        self.text = text
        self.prompt = prompt
        self.tags = tags if tags else {}
    
    def copy(self):
        return Thought(
            self.text,
            id=self.id,
            prompt=self.prompt.copy(),
            tags=self.tags.copy()
            )

EOS_THOUGHT = Thought("", tags={"EOS": None})

def collect_branch(
        thought: Thought,
        max_length: int=-1,
        ignore: Iterable[int]=[],
        ) -> List[Thought]:
    """
    Collects a list of Thoughts from a chosen Thought up to the root.

    Args:
        Thought (Thought): End of branch Thought (has depth 0)
        max_length (int): Max length of the branch
        ignore (List[int]): List of depth of Thoughts to ignore

    Returns:
        List[Thought]: Branch of Thoughts
    """
    thougths = []
    i = j = 0
    while i != max_length:
        if ignore and j < len(ignore) and i == ignore[j]:
            j += 1
        else:
            thougths.append(thought)
        if not thought.parents:
            break
        thought = next(iter(thought.parents))
        i += 1
    thougths.reverse()
    return thougths