import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from langgraph.graph import END, StateGraph

from .analysis_agent import analysis_node
from .learning_agent import learning_node
from .orchestrator import orchestrator_node, route
from .report_agent import make_report_node
from .search_agent import search_node
from .state import MultiAgentState


def build_graph(output_dir: Path):
    report_node = make_report_node(output_dir)

    g = StateGraph(MultiAgentState)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("search", search_node)
    g.add_node("analysis", analysis_node)
    g.add_node("learning", learning_node)
    g.add_node("report", report_node)

    g.set_entry_point("orchestrator")
    g.add_conditional_edges(
        "orchestrator",
        route,
        {
            "search": "search",
            "analysis": "analysis",
            "learning": "learning",
            "report": "report",
            "end": END,
        },
    )
    for node_name in ["search", "analysis", "learning", "report"]:
        g.add_edge(node_name, "orchestrator")

    return g.compile()
