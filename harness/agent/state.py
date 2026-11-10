
from operator import add
from typing import Annotated, Any, Literal

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    # Original user objective
    objective: str

    # Agent execution status
    status: Literal[
        "running",
        "waiting_approval",
        "completed",
        "failed",
    ]

    # Number of executed tool calls
    step_count: int

    # Append execution records across steps
    tool_history: Annotated[
        list[dict[str, Any]],
        add,
    ]

    # Proposed tool call awaiting human approval
    pending_approval: dict[str, Any] | None
