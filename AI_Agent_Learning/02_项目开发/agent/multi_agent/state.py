from typing import Annotated, List, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class MultiAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_query: str
    user_profile: dict
    raw_jobs: List[dict]
    analyzed_jobs: List[dict]
    learning_resources: List[dict]
    report_path: Optional[str]
    next_agent: str
    error: Optional[str]
    iteration_count: int
