
import asyncio
from uuid import uuid4

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage,
)

from harness.agent.loop import OperationsAgent


class MockLLM:

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):

        # First LLM call: request tool
        if not any(
            isinstance(msg, ToolMessage)
            for msg in messages
        ):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_service_status",
                        "args": {
                            "service_name": "payment-service"
                        },
                        "id": "call_mock_1",
                        "type": "tool_call",
                    }
                ],
            )

        # Second LLM call: produce final answer
        return AIMessage(
            content="Service status tool has been executed."
        )


async def main():

    agent = OperationsAgent(
        llm=MockLLM(),
        max_steps=8,
    )

    objective = "Check payment service status"

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
        config={
            "configurable": {
                "thread_id": str(uuid4())
            }
        },
    )

    print("\n=== AGENT RESULT ===")
    print("Status:", result["status"])
    print("Step Count:", result["step_count"])

    print("\n=== TOOL HISTORY ===")
    for record in result["tool_history"]:
        print(record)

    print("\n=== FINAL ANSWER ===")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
