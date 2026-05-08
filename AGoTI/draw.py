from pathlib import Path
from textwrap import wrap
from typing import Any

try:
    from graphviz import Digraph
except ImportError:
    raise ImportError(
        "Rendering dependencies are not installed. "
    )

DEFAULT_NODE_WIDTH = 28
DEFAULT_DIRECTION = "TB"


class GooRenderer:
    def __init__(
        self,
        direction: str = DEFAULT_DIRECTION,
        node_width: int = DEFAULT_NODE_WIDTH,
    ) -> None:
        self.direction = direction
        self.node_width = node_width

    def render(
        self,
        goo_json: dict[str, Any],
        output_path: str | Path,
        format: str = "png",
        view: bool = False,
    ) -> Digraph:
        graph = Digraph("GoO")

        self._configure_graph(graph)
        self._add_nodes(graph, goo_json)
        self._add_edges(graph, goo_json)
        self._add_root_markers(graph, goo_json)
        self._add_output_markers(graph, goo_json)

        graph.render(
            filename=str(output_path),
            format=format,
            cleanup=True,
            view=view,
        )

        return graph

    def _configure_graph(self, graph: Digraph) -> None:
        graph.attr(
            rankdir=self.direction,
            splines="true",
            nodesep="0.6",
            ranksep="0.6",
            pad="0.3",
            bgcolor="white",
        )

        graph.attr(
            "node",
            shape="box",
            style="rounded",
            fontname="Inter",
            fontsize="12",
            margin="0.18,0.12",
            color="#333333",
            penwidth="1.2",
        )

        graph.attr(
            "edge",
            color="#555555",
            arrowsize="0.7",
            penwidth="1.1",
        )

    def _add_nodes(self, graph: Digraph, goo_json: dict[str, Any]) -> None:
        nodes = goo_json.get("nodes", {})

        for node_id, node_data in nodes.items():
            op_class = str(node_data.get("class", "операция"))
            args = node_data.get("args", {})
            name = str(args.get("name", "Без названия"))

            label = self._build_node_label(op_class, name)

            graph.node(
                str(node_id),
                label=label,
                width="2.8",
                fixedsize="false",
            )

    def _add_edges(self, graph: Digraph, goo_json: dict[str, Any]) -> None:
        nodes = goo_json.get("nodes", {})

        for node_id, node_data in nodes.items():
            parents = node_data.get("parents", [])

            for parent_id in parents:
                graph.edge(str(parent_id), str(node_id))

    def _add_root_markers(self, graph: Digraph, goo_json: dict[str, Any]) -> None:
        roots = goo_json.get("roots", [])

        for root_id in roots:
            marker_id = f"root_marker_{root_id}"

            graph.node(
                marker_id,
                label="IN",
                shape="plaintext",
                fontsize="11",
            )

            graph.edge(
                marker_id,
                str(root_id),
                style="dashed",
            )

    def _add_output_markers(self, graph: Digraph, goo_json: dict[str, Any]) -> None:
        outputs = goo_json.get("outputs", {})

        if isinstance(outputs, list):
            outputs = {
                f"output_{i}": node_id
                for i, node_id in enumerate(outputs)
            }

        for output_name, node_id in outputs.items():
            marker_id = f"output_marker_{output_name}"

            graph.node(
                marker_id,
                label=f"OUT: {output_name}",
                shape="plaintext",
                fontsize="11",
            )

            graph.edge(
                str(node_id),
                marker_id,
                style="dashed",
            )

    def _build_node_label(self, op_class: str, name: str) -> str:
        wrapped_name = "\n".join(
            wrap(name, width=self.node_width)
        )

        return f"[{op_class}]\n{wrapped_name}"
