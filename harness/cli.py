"""Command-line entry point for the operations agent."""

import argparse
import asyncio
import json
import sys
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from harness.agent.loop import OperationsAgent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the operations assistant on an objective."
    )
    parser.add_argument(
        "objective",
        nargs="+",
        help="The operations task to perform.",
    )
    parser.add_argument(
        "--provider",
        choices=("api", "local"),
        help="LLM provider; defaults to LLM_PROVIDER or api.",
    )
    parser.add_argument(
        "--model",
        help="Model name; defaults to OPENAI_MODEL or OLLAMA_MODEL.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        help=(
            "Maximum total agent run time; defaults to "
            "AGENT_MAX_EXECUTION_SECONDS or 120."
        ),
    )
    return parser.parse_args()


async def run(
    objective: str,
    provider: str | None,
    model: str | None,
    max_seconds: float | None,
) -> int:
    agent = OperationsAgent(
        llm_provider=provider,
        model=model,
        max_execution_seconds=max_seconds,
    )
    config = {
        "configurable": {
            "thread_id": str(uuid4()),
        },
    }
    state = {
        "objective": objective,
        "messages": [HumanMessage(content=objective)],
        "status": "running",
        "step_count": 0,
        "tool_history": [],
        "pending_approval": None,
    }

    result = await agent.graph.ainvoke(state, config=config)

    while result.get("__interrupt__"):
        for pending in result["__interrupt__"]:
            approval = pending.value
            print("\nApproval required:")
            print(json.dumps(approval, indent=2, ensure_ascii=False))
            answer = input("Approve? [y/N] ").strip().lower()
            decision = (
                "approve" if answer in {"y", "yes"} else "reject"
            )
            result = await agent.graph.ainvoke(
                Command(
                    resume={
                        "decision": decision,
                        "tool_call_id": approval.get(
                            "tool_call_id"
                        ),
                    }
                ),
                config=config,
            )

    print(f"\nStatus: {result['status']}")
    print(f"Tool steps: {result['step_count']}")
    print("\nTool history:")
    print(json.dumps(
        result.get("tool_history", []),
        indent=2,
        ensure_ascii=False,
        default=str,
    ))
    if result.get("messages"):
        print("\nAssistant:")
        print(result["messages"][-1].content)

    return 0 if result["status"] == "completed" else 1


def main() -> None:
    args = parse_args()
    objective = " ".join(args.objective)
    try:
        exit_code = asyncio.run(
            run(
                objective,
                args.provider,
                args.model,
                args.max_seconds,
            )
        )
    except (EOFError, KeyboardInterrupt):
        print("\nRun cancelled.", file=sys.stderr)
        exit_code = 130
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
