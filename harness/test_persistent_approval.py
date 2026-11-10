
import argparse
import asyncio
import json

from pathlib import Path
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from harness.agent.loop import OperationsAgent


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "agent_checkpoints.db"


class MockLLM:

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        # Check whether a tool has already returned a result
        tool_results = [
            msg for msg in messages
            if isinstance(msg, ToolMessage)
        ]

        if tool_results:
            result = json.loads(tool_results[-1].content)

            if result["ok"]:
                text = "Incident created successfully."
            else:
                text = (
                    "Incident was not created: "
                    + result["error"]["code"]
                )

            return AIMessage(content=text)

        # Propose creating an incident
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "create_incident",
                    "args": {
                        "title": "Payment Service Database Failure",
                        "description": (
                            "Payment processing failed because "
                            "the database connection was unavailable."
                        ),
                        "severity": "high",
                    },
                    "id": "create_incident_001",
                    "type": "tool_call",
                }
            ],
        )


async def start(agent, config):

    objective = "Create an incident for payment database failure"

    result = await agent.graph.ainvoke(
        {
            "objective": objective,
            "messages": [
                HumanMessage(content=objective)
            ],
            "status": "running",
            "step_count": 0,
            "tool_history": [],
            "pending_approval": None,
        },
        config=config,
        durability="sync",
    )

    interrupts = result.get("__interrupt__", ())

    if not interrupts:
        raise RuntimeError("Expected approval interrupt")

    print("\n=== AGENT PAUSED ===")
    print(json.dumps(
        interrupts[0].value,
        indent=2,
    ))

    print("\nThread ID:", config["configurable"]["thread_id"])
    print("Checkpoint DB:", DB_PATH)
    print("You may now close this process.")


async def resume(agent, config):

    # Load persisted checkpoint
    snapshot = await agent.graph.aget_state(config)

    if not snapshot or "execute_tools" not in snapshot.next:
        raise RuntimeError(
            "No pending incident approval found for this thread"
        )

    last_message = snapshot.values["messages"][-1]

    if not isinstance(last_message, AIMessage):
        raise RuntimeError("Expected a pending AI tool call")

    if len(last_message.tool_calls) != 1:
        raise RuntimeError("Expected exactly one tool call")

    tool_call = last_message.tool_calls[0]

    if tool_call["name"] != "create_incident":
        raise RuntimeError("Unexpected pending tool")

    print("\n=== RESTORED APPROVAL REQUEST ===")
    print("Tool:", tool_call["name"])
    print(json.dumps(tool_call["args"], indent=2))

    answer = input(
        "\nApprove this incident? (yes/no): "
    ).strip().lower()

    decision = "approve" if answer == "yes" else "reject"

    result = await agent.graph.ainvoke(
        Command(
            resume={
                "decision": decision,
                "tool_call_id": tool_call["id"],
            }
        ),
        config=config,
        durability="sync",
    )

    print("\n=== RESUMED RESULT ===")
    print("Status:", result["status"])
    print("Steps:", result["step_count"])
    print("Final:", result["messages"][-1].content)

    print("\n=== TOOL HISTORY ===")
    for record in result["tool_history"]:
        print(json.dumps(record, indent=2))


async def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "action",
        choices=["start", "resume"],
    )

    parser.add_argument(
        "--thread-id",
        type=str,
    )

    args = parser.parse_args()

    if args.action == "resume" and not args.thread_id:
        parser.error("--thread-id is required for resume")

    thread_id = (
        args.thread_id
        if args.action == "resume"
        else str(uuid4())
    )

    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "recursion_limit": 30,
    }

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Persistent checkpoint
    async with AsyncSqliteSaver.from_conn_string(
        str(DB_PATH)
    ) as checkpointer:

        agent = OperationsAgent(
            llm=MockLLM(),
            max_steps=8,
            checkpointer=checkpointer,
        )

        if args.action == "start":
            await start(agent, config)
        else:
            await resume(agent, config)


if __name__ == "__main__":
    asyncio.run(main())
