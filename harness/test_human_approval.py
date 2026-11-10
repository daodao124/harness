
import asyncio
import json
import sqlite3
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command

from harness.agent.loop import OperationsAgent
from harness.tool.create_incident import DB_PATH


class MockLLM:

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):

        tool_results = [
            message for message in messages
            if isinstance(message, ToolMessage)
        ]

        # First turn: propose incident creation
        if not tool_results:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_incident",
                        "args": {
                            "title": "Payment Service Database Failure",
                            "description": (
                                "Payment Service is affected by "
                                "DATABASE_CONNECTION_ERROR."
                            ),
                            "severity": "high",
                        },
                        "id": "incident_call_001",
                        "type": "tool_call",
                    }
                ],
            )

        # After tool result: generate final answer
        result = json.loads(tool_results[-1].content)

        if result["ok"]:
            content = "Incident created successfully."
        elif result["error"]["code"] == "USER_REJECTED":
            content = "Incident creation was rejected by the user."
        else:
            content = f"Incident not created: {result['error']}"

        return AIMessage(content=content)


def count_incidents() -> int:
    if not DB_PATH.exists():
        return 0

    with sqlite3.connect(DB_PATH) as conn:
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM incidents"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0


async def main():

    agent = OperationsAgent(
        llm=MockLLM(),
        max_steps=8,
    )

    thread_id = str(uuid4())

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    objective = "Create an incident for payment database failure"

    before = count_incidents()

    # Step 1: Start Agent
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
    )

    # Step 2: Check interrupt
    interrupts = result.get("__interrupt__", ())

    if not interrupts:
        raise RuntimeError("Expected an approval interrupt")

    approval_request = interrupts[0].value

    print("\n=== HUMAN APPROVAL REQUIRED ===")
    print(json.dumps(approval_request, indent=2))

    # Verify that no incident was created yet
    assert count_incidents() == before

    # Step 3: Ask actual user
    answer = input(
        "\nApprove incident creation? (yes/no): "
    ).strip().lower()

    decision = "approve" if answer == "yes" else "reject"

    # Step 4: Resume SAME graph and SAME thread
    resumed = await agent.graph.ainvoke(
        Command(
            resume={
                "decision": decision,
                "tool_call_id": approval_request["tool_call_id"],
            }
        ),
        config=config,
    )

    print("\n=== FINAL RESULT ===")
    print("Status:", resumed["status"])
    print("Steps:", resumed["step_count"])
    print("Final answer:", resumed["messages"][-1].content)

    print("\n=== TOOL HISTORY ===")
    for record in resumed["tool_history"]:
        print(json.dumps(record, indent=2))

    after = count_incidents()
    print(f"\nIncident count: {before} -> {after}")

    if decision == "approve":
        assert after == before + 1
        assert resumed["tool_history"][-1]["result"]["ok"]
    else:
        assert after == before
        assert (
            resumed["tool_history"][-1]["result"]["error"]["code"]
            == "USER_REJECTED"
        )

    print("\nHITL TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
