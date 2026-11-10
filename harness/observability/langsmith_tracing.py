
from collections.abc import Awaitable, Callable

from langsmith import trace


async def trace_tool_execution(
    tool_name: str,
    operation: Callable[[], Awaitable[dict]],
    *,
    tool_call_id: str | None = None,
) -> dict:
    """
    Create a LangSmith trace for one tool execution.

    Does not expose raw arguments or approval tokens.
    """

    metadata = (
        {"tool_call_id": tool_call_id}
        if tool_call_id
        else {}
    )

    async with trace(
        name=f"tool:{tool_name}",
        run_type="tool",
        inputs={"tool_name": tool_name},
        metadata=metadata,
    ) as run:

        result = await operation()

        error = result.get("error") or {}

        run.end(
            outputs={
                "ok": result.get("ok"),
                "error_code": error.get("code"),
                "duration_ms": result.get("duration_ms"),
                "attempts": result.get("attempts"),
            }
        )

        return result


def trace_approval_decision(
    *,
    tool_name: str,
    tool_call_id: str,
    decision: str,
) -> None:
    """
    Trace human approval without exposing
    incident details or approval tokens.
    """

    with trace(
        name="human_approval_decision",
        run_type="chain",
        inputs={
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
        },
    ) as run:

        run.end(
            outputs={
                "decision": decision,
            }
        )
