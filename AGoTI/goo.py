from typing import Iterable, List, Dict, Optional
import asyncio
import json

from .operations import Operation
from .thoughts import Thought
from .utils import OrientedGraphNode, OrientedGraph

class GraphOfOperations(OrientedGraph):
    def __init__(
            self,
            nodes: Iterable[OrientedGraphNode] | Dict[int, OrientedGraphNode],
            roots: Iterable[Operation],
            outputs: List[Operation] | Dict[str, Operation]):
        super().__init__(nodes)
        self.roots = list(roots)
        self.outputs = outputs
    
    async def run(self, **kwargs) -> List[str] | Dict[str, str]:
        tasks = []
        for node in self.roots:
            tasks.append(asyncio.create_task(node.run(**kwargs)))
        await asyncio.gather(*tasks)
        return self.get_output()
    
    def get_output(self) -> List[str] | Dict[str, List[str]]:
        if type(self.outputs) is list:
            out = []
            for operation in self.outputs:
                thoughts = [thought for thought in operation.thoughts if not thought.tags.get("no_send", False)]
                out += list(map(lambda x: x.text, thoughts))
        elif type(self.outputs) is dict:
            out = {}
            for key, operation in self.outputs.items():
                thoughts = [thought for thought in operation.thoughts if not thought.tags.get("no_send", False)]
                out[key] = list(map(lambda x: x.text, thoughts))
        return out

    def get_got_json(self) -> Dict:
        got_json = {}
        for id, node in self.id_to_node.items():
            for thought in node.thoughts:
                thought_info = {
                    "parents": [parent.id for parent in thought.parents],
                    "text": thought.text,
                    "prompt": thought.prompt,
                    "tags": thought.tags,
                    "op_id": id
                }
                got_json[thought.id] = thought_info
        return got_json

    def reset(self) -> None:
        for node in self.id_to_node.values():
            node.reset(propogate=False)

    def __del__(self):
        for node in self.id_to_node.values():
            node.clear_refs()

    def copy(self):
        #TODO: implement smart copy
        raise NotImplementedError()


def load_goo_json(goo_path: str, name_to_class: Dict, got_path: Optional[str]=None, throw_exceptions: bool=True) -> Optional[GraphOfOperations]:
    with open(goo_path, mode="r") as file:
        goo_json = json.load(file)
    if got_path:
        with open(got_path, mode="r") as file:
            got_json = json.load(file)
    else:
        got_json = None
    return parse_goo_json(goo_json, name_to_class, got_json, throw_exceptions)

def parse_goo_json(goo_json: Dict, name_to_class: Dict, got_json: Optional[Dict]=None, throw_exceptions: bool=True) -> Optional[GraphOfOperations]:
    id_to_op: Dict[int, Operation] = {}

    if not set(goo_json.keys()).issuperset({"nodes", "roots", "outputs"}):
        if throw_exceptions: raise Exception("Unable to load GoO from json - wrong format")
        return None

    for id, info in goo_json["nodes"].items():
        if isinstance(id, str):
            id = int(id)
        elif not isinstance(id, int):
            if throw_exceptions: raise Exception("Operation id must be an integer")
            return None
        if not isinstance(info, dict):
            if throw_exceptions: raise Exception("Incorrect operation info format")
            return None
        
        class_name = info.get("class", None)
        if class_name is None:
            if throw_exceptions: raise Exception("Each operation in json must have `class` field!")
            return None
        
        operation_class = name_to_class.get(class_name, None)
        if operation_class is None:
            if throw_exceptions: raise Exception(f"No such class name in GoO config: \"{class_name}\"")
            return None
        
        params_no_parent = {k: v for k, v in info["args"].items() if k != "parents"}
        id_to_op[id] = operation_class(id=id, **params_no_parent)
    
    for id, info in goo_json["nodes"].items():
        id = int(id)
        parent_ids = info["parents"]
        if not set(parent_ids).issubset(set(id_to_op.keys())):
            if throw_exceptions: raise Exception(f"No parent nodes with such ids: \"{parent_ids}\"")
            return None
        id_to_op[id].add_parents([id_to_op[i] for i in parent_ids])
    
    roots: List[Operation] = []
    for id in goo_json["roots"]:
        id = int(id)
        roots.append(id_to_op[id])
    
    if isinstance(goo_json["outputs"], list):
        outputs: List[Operation] = []
        for id in goo_json["outputs"]:
            id = int(id)
            outputs.append(id_to_op[id])
    elif isinstance(goo_json["outputs"], dict):
        outputs = {}
        for key, id in goo_json["outputs"].items():
            id = int(id)
            outputs[key] = id_to_op[id]
    
    if got_json:
        id_to_thought: Dict[int, Thought] = {}
        for id, thought_info in got_json.items():
            id = int(id)
            id_to_thought[id] = Thought(
                thought_info["text"],
                None,
                thought_info["prompt"],
                thought_info["tags"],
                id,
                )
        
        for id, thought_info in got_json.items():
            thought = id_to_thought[int(id)]
            thought.add_parents(list(map(lambda x: id_to_thought[x], thought_info["parents"])))
            id_to_op[thought_info["op_id"]].thoughts.append(thought)

    return GraphOfOperations(id_to_op, roots, outputs)
