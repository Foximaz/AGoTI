from typing import Iterable, List, Dict, Any
import asyncio
import json
from . import operations as op
from .utils import OrientedGraphNode, OrientedGraph

class GraphOfOperations(OrientedGraph):
    def __init__(
            self,
            nodes: Iterable[OrientedGraphNode] | Dict[int, OrientedGraphNode],
            roots: Iterable[op.Operation],
            outputs: List[op.Operation] | Dict[Any, op.Operation]):
        super().__init__(nodes)
        self.roots = list(roots)
        self.outputs = outputs
    
    async def run(self, **kwargs) -> List[str] | Dict[Any, str]:
        tasks = []
        for node in self.roots:
            tasks.append(asyncio.create_task(node.run(**kwargs)))
        await asyncio.gather(*tasks)
        if type(self.outputs) is list:
            out = []
            for operation in self.outputs:
                out += list(map(lambda x: x.text, operation.thoughts))
        elif type(self.outputs) is dict:
            out = {}
            for key, operation in self.outputs.values():
                out[key] = list(map(lambda x: x.text, operation.thoughts))
        return out
    
    def clear(self) -> None:
        for node in self.nodes:
            node.clear(propogate=False)

    def copy(self):
        #TODO: implement smart copy
        raise Exception("Not implemented yet!")


def load_goo_json(path: str, name_to_class: Dict):
    with open(path, mode="r") as file:
        goo_json = json.load(file)
    return parse_goo_json(goo_json, name_to_class)

def parse_goo_json(goo_json: Dict, name_to_class: Dict):
    id_to_op = {}

    for id, info in goo_json["nodes"].items():
        id = int(id)
        operation_class = name_to_class[info.get("class", None)]
        assert operation_class != None, "Each operation in json must have `class` field!"
        params_no_parent = {k: v for k, v in info["args"].items() if k != "parents"}
        id_to_op[id] = operation_class(**params_no_parent)
    
    for id, info in goo_json["nodes"].items():
        id = int(id)
        parent_ids = info["args"].get("parents", None)
        id_to_op[id].add_parents([id_to_op[i] for i in parent_ids])
    
    roots = []
    for id in goo_json["roots"]:
        id = int(id)
        roots.append(id_to_op[id])
    
    outputs = []
    for id in goo_json["outputs"]:
        id = int(id)
        outputs.append(id_to_op[id])
    
    return GraphOfOperations(id_to_op, roots, outputs)
