from .state import MultiAgentState


def orchestrator_node(state: MultiAgentState) -> dict:
    count = state.get("iteration_count", 0) + 1
    print(f"\n[Orchestrator] 第 {count} 次调度", flush=True)

    if not state.get("raw_jobs"):
        next_agent = "search"
    elif not state.get("analyzed_jobs"):
        next_agent = "analysis"
    elif not state.get("learning_resources"):
        next_agent = "learning"
    elif not state.get("report_path"):
        next_agent = "report"
    else:
        next_agent = "end"

    print(f"[Orchestrator] → {next_agent}", flush=True)
    return {"next_agent": next_agent, "iteration_count": count}


def route(state: MultiAgentState) -> str:
    return state.get("next_agent", "end")
