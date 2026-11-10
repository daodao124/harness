import asyncio
import sqlite3
from dataclasses import replace
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from harness.agent.loop import OperationsAgent
from harness.core.executor import ToolExecutor
from harness.core.registry import TOOL_REGISTRY, get_tool
from harness.tool import create_incident as incident_module


def tool_call(name, args, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self.responses.pop(0)


class SlowLLM(ScriptedLLM):
    async def ainvoke(self, messages):
        await asyncio.sleep(0.1)
        return AIMessage(content="too late")


def make_agent(llm, **kwargs):
    return OperationsAgent(llm=llm, **kwargs)


def invoke(agent, objective="test objective"):
    return asyncio.run(
        agent.graph.ainvoke(
            {
                "objective": objective,
                "messages": [HumanMessage(content=objective)],
                "status": "running",
                "step_count": 0,
                "tool_history": [],
                "pending_approval": None,
            },
            config={"configurable": {"thread_id": str(uuid4())}},
        )
    )


def replace_status_tool(monkeypatch, function, *, timeout_seconds=7):
    original = get_tool("get_service_status")
    monkeypatch.setitem(
        TOOL_REGISTRY,
        "get_service_status",
        replace(
            original,
            function=function,
            timeout_seconds=timeout_seconds,
        ),
    )


def status_args():
    return {"service_name": "payment-service"}


def test_agent_runs_tool_and_returns_final_answer(monkeypatch):
    async def fake_status(service_name):
        return {
            "service_name": service_name,
            "status": "healthy",
            "message": "All good",
        }

    monkeypatch.setitem(
        TOOL_REGISTRY,
        "get_service_status",
        replace(
            get_tool("get_service_status"),
            function=fake_status,
        ),
    )
    agent = make_agent(
        ScriptedLLM(
            tool_call("get_service_status", status_args()),
            AIMessage(content="The service is healthy."),
        )
    )

    result = invoke(agent)

    assert result["status"] == "completed"
    assert result["step_count"] == 1
    assert result["tool_history"][0]["result"]["ok"] is True
    assert result["messages"][-1].content == "The service is healthy."


def test_invalid_tool_arguments_are_recorded(monkeypatch):
    async def unused_status(service_name):
        raise AssertionError("invalid arguments must not call the tool")

    replace_status_tool(monkeypatch, unused_status)
    agent = make_agent(
        ScriptedLLM(
            tool_call(
                "get_service_status",
                {"service_name": "unknown-service"},
            ),
            AIMessage(content="The tool arguments were invalid."),
        )
    )

    result = invoke(agent)

    assert result["status"] == "completed"
    assert result["tool_history"][0]["result"]["error"]["code"] == (
        "INVALID_ARGUMENTS"
    )


def test_invalid_tool_output_is_reported(monkeypatch):
    async def bad_status(service_name):
        return {"status": "not-a-valid-status"}

    replace_status_tool(monkeypatch, bad_status)
    agent = make_agent(
        ScriptedLLM(
            tool_call("get_service_status", status_args()),
            AIMessage(content="The service response was invalid."),
        )
    )

    result = invoke(agent)

    assert result["tool_history"][0]["result"]["error"]["code"] == (
        "INVALID_TOOL_OUTPUT"
    )


def test_tool_timeout_is_returned_by_executor(monkeypatch):
    async def slow_status(service_name):
        await asyncio.sleep(0.1)
        return {
            "service_name": service_name,
            "status": "healthy",
        }

    replace_status_tool(
        monkeypatch,
        slow_status,
        timeout_seconds=0.01,
    )
    result = asyncio.run(
        ToolExecutor().execute(
            "get_service_status",
            status_args(),
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "TOOL_TIMEOUT"


def test_agent_stops_at_step_limit(monkeypatch):
    async def fake_status(service_name):
        return {"service_name": service_name, "status": "healthy"}

    replace_status_tool(monkeypatch, fake_status)
    agent = make_agent(
        ScriptedLLM(
            tool_call("get_service_status", status_args()),
            tool_call("get_service_status", status_args(), "call-2"),
        ),
        max_steps=1,
    )

    result = invoke(agent)

    assert result["status"] == "failed"
    assert result["step_count"] == 1
    assert result["messages"][-1].content == "Maximum tool steps reached."


def test_agent_stops_when_llm_exceeds_total_deadline():
    agent = make_agent(
        SlowLLM(),
        max_execution_seconds=0.01,
    )

    result = invoke(agent)

    assert result["status"] == "failed"
    assert result["messages"][-1].content == "Execution time limit reached."


def test_malformed_llm_response_fails_cleanly():
    agent = make_agent(ScriptedLLM(object()))

    result = invoke(agent)

    assert result["status"] == "failed"
    assert result["messages"][-1].content == (
        "LLM returned a malformed response."
    )


def test_incident_creation_pauses_for_approval_and_rejection_writes_nothing(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "incidents.db"
    monkeypatch.setattr(incident_module, "DB_PATH", db_path)
    incident_args = {
        "title": "Payment service outage",
        "description": "The payment service is unavailable.",
        "severity": "high",
    }
    agent = make_agent(
        ScriptedLLM(
            tool_call("create_incident", incident_args, "incident-1"),
            AIMessage(content="Incident creation was rejected."),
        )
    )
    config = {"configurable": {"thread_id": str(uuid4())}}
    objective = "Create an incident for the outage"
    state = {
        "objective": objective,
        "messages": [HumanMessage(content=objective)],
        "status": "running",
        "step_count": 0,
        "tool_history": [],
        "pending_approval": None,
    }

    paused = asyncio.run(agent.graph.ainvoke(state, config=config))

    assert paused["__interrupt__"]
    assert not db_path.exists()
    approval = paused["__interrupt__"][0].value
    result = asyncio.run(
        agent.graph.ainvoke(
            Command(
                resume={
                    "decision": "reject",
                    "tool_call_id": approval["tool_call_id"],
                }
            ),
            config=config,
        )
    )

    assert result["status"] == "completed"
    assert result["tool_history"][-1]["result"]["error"]["code"] == (
        "USER_REJECTED"
    )
    assert not db_path.exists()


def test_incident_executor_requires_and_consumes_approval(monkeypatch, tmp_path):
    db_path = tmp_path / "incidents.db"
    monkeypatch.setattr(incident_module, "DB_PATH", db_path)
    arguments = {
        "title": "Payment service outage",
        "description": "The payment service is unavailable.",
        "severity": "high",
    }
    executor = ToolExecutor()

    denied = asyncio.run(
        executor.execute("create_incident", arguments)
    )
    assert denied["error"]["code"] == "APPROVAL_REQUIRED"
    assert not db_path.exists()

    approval = executor.issue_approval("create_incident", arguments)
    created = asyncio.run(
        executor.execute(
            "create_incident",
            arguments,
            approval_token=approval,
            execution_id="test-execution-1",
        )
    )

    assert created["ok"] is True
    with sqlite3.connect(db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM incidents"
        ).fetchone()[0]
    assert count == 1
