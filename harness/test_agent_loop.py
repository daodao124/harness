
import asyncio
from uuid import uuid4

from langchain_core.messages import HumanMessage

from harness.agent.loop import OperationsAgent


async def main():

    # Initialize Agent
    agent = OperationsAgent(max_steps=8)

    objective = (
        "Check the payment service status. "
        "If it is down, investigate error logs "
        "and search the knowledge base."
    )

    config = {
        "configurable": {
            "thread_id": str(uuid4()),
        },
        "recursion_limit": 30,
    }

    # Execute LangGraph AgentLoop
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

    print("\n=== AGENT RESULT ===")
    print("Status:", result["status"])
    print("Steps:", result["step_count"])

    print("\n=== TOOL HISTORY ===")
    for record in result["tool_history"]:
        print(record)

    print("\n=== LAST MESSAGE ===")
    print(result["messages"][-1].content)

    if result["status"] == "waiting_approval":
        print("\n=== PENDING APPROVAL ===")
        print(result["pending_approval"])


if __name__ == "__main__":
    asyncio.run(main())
