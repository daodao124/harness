
import json
import logging
import math
import os
import time
import asyncio

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, RetryPolicy
from langgraph.func import task

from pydantic import ValidationError

from harness.agent.state import AgentState
from harness.agent.prompt import SYSTEM_PROMPT

from harness.core.executor import ToolExecutor
from harness.core.registry import (
    get_tool_definitions,
    get_tool,
)

from harness.observability.langsmith_tracing import (
    trace_tool_execution,
    trace_approval_decision,
)


logger = logging.getLogger(__name__)


# -----------------------------------
# Read-only tools
# -----------------------------------

READ_TOOLS = {
    "get_service_status",
    "get_error_logs",
    "search_knowledge_base",
}


RETRYABLE_ERRORS = {
    "NETWORK_ERROR",
    "NETWORK_TIMEOUT",
    "TOOL_TIMEOUT",
    "RATE_LIMITED",
    "UPSTREAM_UNAVAILABLE",
}


class RetryableToolError(Exception):

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# -----------------------------------
# Read Tool Task + Retry + Tracing
# -----------------------------------

@task(
    retry_policy=RetryPolicy(
        max_attempts=3,
        initial_interval=0.5,
        retry_on=RetryableToolError,
    )
)
async def execute_read_task(
    tool_name: str,
    arguments: dict,
    tool_call_id: str | None = None,
) -> dict:

    if tool_name not in READ_TOOLS:
        raise ValueError(
            "Only read tools are allowed"
        )

    executor = ToolExecutor()

    result = await trace_tool_execution(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        operation=lambda: executor.execute(
            tool_name=tool_name,
            arguments=arguments,
        ),
    )

    error = result.get("error") or {}
    error_code = error.get("code")

    if error_code in RETRYABLE_ERRORS:
        raise RetryableToolError(error_code)

    return result

# ===================================
# Operations Agent
# ===================================

class OperationsAgent:

    def __init__(
        self,
        model: str | None = None,
        max_steps: int = 8,
        llm=None,
        llm_provider: str | None = None,
        checkpointer=None,
        max_execution_seconds: float | None = None,
    ):

        if max_steps < 1:
            raise ValueError(
                "max_steps must be positive"
            )

        self.max_steps = max_steps
        self.max_execution_seconds = (
            max_execution_seconds
            if max_execution_seconds is not None
            else float(os.getenv("AGENT_MAX_EXECUTION_SECONDS", "120"))
        )
        if (
            not math.isfinite(self.max_execution_seconds)
            or self.max_execution_seconds <= 0
        ):
            raise ValueError(
                "max_execution_seconds must be a positive finite number"
            )

        # A supplied model instance takes precedence. Otherwise select the
        # provider explicitly or through LLM_PROVIDER (api/local).
        if llm is not None:
            self.llm = llm
            self.llm_provider = "custom"
        else:
            provider = (
                llm_provider or os.getenv("LLM_PROVIDER", "api")
            ).strip().lower()

            if provider in {"api", "openai"}:
                self.llm_provider = "api"
                self.llm = ChatOpenAI(
                    model=model or os.getenv(
                        "OPENAI_MODEL",
                        "gpt-4.1-mini",
                    ),
                    base_url=os.getenv("OPENAI_BASE_URL") or None,
                    temperature=0,
                    timeout=30,
                    max_retries=1,
                )
            elif provider in {"local", "ollama"}:
                self.llm_provider = "local"
                self.llm = ChatOllama(
                    model=model or os.getenv(
                        "OLLAMA_MODEL",
                        "qwen3:8b",
                    ),
                    base_url=os.getenv(
                        "OLLAMA_BASE_URL",
                        "http://localhost:11434",
                    ),
                    temperature=0,
                )
            else:
                raise ValueError(
                    "LLM provider must be 'api' or 'local'."
                )

        # Bind tool definitions
        tool_definitions = get_tool_definitions()
        if self.llm_provider == "api":
            self.llm_with_tools = self.llm.bind_tools(
                tool_definitions,
                parallel_tool_calls=False,
            )
        else:
            # Ollama does not accept OpenAI's parallel_tool_calls option.
            # The loop itself rejects responses containing multiple calls.
            self.llm_with_tools = self.llm.bind_tools(tool_definitions)

        # Custom ToolExecutor
        self.executor = ToolExecutor()

        # LangGraph Checkpointer
        self.checkpointer = (
            checkpointer
            if checkpointer is not None
            else InMemorySaver()
        )

        # Compile LangGraph
        self.graph = self.build_graph()

    # -----------------------------------
    # Node 1: Call LLM
    # -----------------------------------

    def initialize_execution(self, state: AgentState) -> dict:
        """Set one deadline for the run; resumes keep the checkpointed value."""
        if state.get("deadline_at") is not None:
            return {}
        return {
            "deadline_at": (
                time.time() + self.max_execution_seconds
            )
        }

    async def call_llm(
        self,
        state: AgentState,
    ) -> dict:

        if state["status"] == "waiting_approval":
            return {}

        deadline_at = state.get("deadline_at")
        remaining = (
            deadline_at - time.time()
            if deadline_at is not None
            else self.max_execution_seconds
        )
        if remaining <= 0:
            return {
                "status": "failed",
                "messages": [
                    AIMessage(content="Execution time limit reached.")
                ],
            }

        if state["step_count"] >= self.max_steps:
            return {
                "status": "failed",
                "messages": [
                    AIMessage(
                        content="Maximum tool steps reached."
                    )
                ],
            }

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            *state["messages"],
        ]

        try:
            # LangGraph + LangChain automatically
            # generate traces when LangSmith is enabled.
            response = await asyncio.wait_for(
                self.llm_with_tools.ainvoke(messages),
                timeout=remaining,
            )

        except asyncio.TimeoutError:
            logger.warning("Agent execution time limit reached during LLM call")
            return {
                "status": "failed",
                "messages": [
                    AIMessage(content="Execution time limit reached.")
                ],
            }

        except Exception:
            logger.exception(
                "LLM invocation failed"
            )

            return {
                "status": "failed",
                "messages": [
                    AIMessage(
                        content="LLM request failed."
                    )
                ],
            }

        if not isinstance(response, AIMessage):
            logger.error(
                "LLM returned an unexpected response type: %s",
                type(response).__name__,
            )
            return {
                "status": "failed",
                "messages": [
                    AIMessage(
                        content="LLM returned a malformed response."
                    )
                ],
            }

        # Invalid tool calls
        if response.invalid_tool_calls:
            return {
                "messages": [response],
                "status": "failed",
            }

        # Final answer
        if not response.tool_calls:
            return {
                "messages": [response],
                "status": "completed",
            }

        # Only one tool call per turn
        if len(response.tool_calls) > 1:
            return {
                "status": "failed",
                "messages": [
                    AIMessage(
                        content=(
                            "Multiple tool calls "
                            "are not supported."
                        )
                    )
                ],
            }

        return {
            "messages": [response],
            "status": "running",
        }

    # -----------------------------------
    # Router: After LLM
    # -----------------------------------

    def route_after_llm(
        self,
        state: AgentState,
    ):

        if state["status"] != "running":
            return END

        last_message = state["messages"][-1]

        if (
            isinstance(last_message, AIMessage)
            and last_message.tool_calls
        ):
            return "execute_tools"

        return END

    # -----------------------------------
    # Node 2: Execute Tools
    # -----------------------------------

    async def execute_tools(
        self,
        state: AgentState,
        config: RunnableConfig,
    ) -> dict:

        last_message = state["messages"][-1]

        # One tool call per turn
        if (
            not isinstance(last_message, AIMessage)
            or len(last_message.tool_calls) != 1
        ):
            return {
                "status": "failed",
                "messages": [
                    AIMessage(
                        content=(
                            "Expected exactly one tool call."
                        )
                    )
                ],
            }

        tool_call = last_message.tool_calls[0]

        tool_name = tool_call["name"]
        arguments = tool_call["args"]
        tool_call_id = tool_call["id"]

        step_count = state["step_count"]
        status = "running"
        deadline_at = state.get("deadline_at")

        def error_result(
            code: str,
            message: str,
        ) -> dict:

            return {
                "ok": False,
                "tool": tool_name,
                "data": None,
                "error": {
                    "code": code,
                    "message": message,
                },
            }

        # Validate tool call ID
        if not tool_call_id:
            return {
                "status": "failed",
                "messages": [
                    AIMessage(
                        content="Tool call ID is missing."
                    )
                ],
            }

        # -----------------------------------
        # Maximum steps
        # -----------------------------------

        if step_count >= self.max_steps:

            result = error_result(
                "STEP_LIMIT_REACHED",
                "Maximum tool steps reached.",
            )

            status = "failed"

        elif (
            deadline_at is not None
            and deadline_at <= time.time()
        ):

            result = error_result(
                "EXECUTION_TIMEOUT",
                "Agent execution time limit reached.",
            )
            status = "failed"

        # -----------------------------------
        # Write Tool: Create Incident
        # -----------------------------------

        elif tool_name == "create_incident":

            tool_spec = get_tool(tool_name)

            if tool_spec is None:

                result = error_result(
                    "UNKNOWN_TOOL",
                    "Tool is not registered.",
                )

            else:

                try:
                    validated_args = (
                        tool_spec.input_schema
                        .model_validate(arguments)
                        .model_dump(mode="json")
                    )

                except (
                    ValidationError,
                    TypeError,
                    ValueError,
                ):

                    result = error_result(
                        "INVALID_ARGUMENTS",
                        "Invalid incident arguments.",
                    )

                else:

                    # -----------------------------------
                    # Human Approval
                    # -----------------------------------

                    # No database write happens before
                    # this interrupt.
                    decision = interrupt({
                        "type": "incident_approval",
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "arguments": validated_args,
                        "message": (
                            "Approve creating this incident?"
                        ),
                    })

                    valid_decision = (
                        isinstance(decision, dict)
                        and decision.get("tool_call_id")
                        == tool_call_id
                        and decision.get("decision")
                        in {"approve", "reject"}
                    )

                    decision_label = (
                        decision["decision"]
                        if valid_decision
                        else "invalid"
                    )

                    # Trace human approval decision
                    trace_approval_decision(
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        decision=decision_label,
                    )

                    # Invalid approval response
                    if not valid_decision:

                        result = error_result(
                            "INVALID_APPROVAL_RESPONSE",
                            "Invalid approval response.",
                        )

                    # Human rejects
                    elif decision["decision"] == "reject":

                        result = error_result(
                            "USER_REJECTED",
                            "User rejected incident creation.",
                        )

                    # Human approves
                    else:
                        if (
                            deadline_at is not None
                            and deadline_at <= time.time()
                        ):
                            result = error_result(
                                "EXECUTION_TIMEOUT",
                                "Agent execution time limit reached.",
                            )
                            status = "failed"
                            # Do not issue an approval grant or write after
                            # the run deadline has elapsed.
                        else:
                            thread_id = (
                                config.get(
                                    "configurable", {}
                                ).get("thread_id")
                            )

                            if not thread_id:

                                result = error_result(
                                    "INVALID_THREAD_ID",
                                    "Thread ID is required.",
                                )

                            else:

                                # Stable idempotency key
                                execution_id = (
                                    f"{thread_id}:{tool_call_id}"
                                )

                                # Issue one-time approval token
                                approval_token = (
                                    self.executor.issue_approval(
                                        tool_name=tool_name,
                                        arguments=validated_args,
                                    )
                                )

                                # Execute with LangSmith trace
                                try:
                                    result = await asyncio.wait_for(
                                        trace_tool_execution(
                                            tool_name=tool_name,
                                            tool_call_id=tool_call_id,
                                            operation=lambda: (
                                                self.executor.execute(
                                                    tool_name=tool_name,
                                                    arguments=validated_args,
                                                    approval_token=approval_token,
                                                    execution_id=execution_id,
                                                )
                                            ),
                                        ),
                                        timeout=(
                                            deadline_at - time.time()
                                            if deadline_at is not None
                                            else self.max_execution_seconds
                                        ),
                                    )
                                except asyncio.TimeoutError:
                                    result = error_result(
                                        "EXECUTION_TIMEOUT",
                                        "Agent execution time limit reached.",
                                    )
                                    status = "failed"

        # -----------------------------------
        # Read Tools + Retry + Tracing
        # -----------------------------------

        elif tool_name in READ_TOOLS:

            try:
                timeout = (
                    deadline_at - time.time()
                    if deadline_at is not None
                    else self.max_execution_seconds
                )
                result = await asyncio.wait_for(
                    execute_read_task(
                        tool_name,
                        arguments,
                        tool_call_id,
                    ),
                    timeout=max(0.001, timeout),
                )

            except RetryableToolError as exc:

                result = error_result(
                    exc.code,
                    "Retry attempts exhausted.",
                )

            except asyncio.TimeoutError:
                result = error_result(
                    "EXECUTION_TIMEOUT",
                    "Agent execution time limit reached.",
                )
                status = "failed"

        # -----------------------------------
        # Unknown or Other Tools
        # -----------------------------------

        else:

            timeout = (
                deadline_at - time.time()
                if deadline_at is not None
                else self.max_execution_seconds
            )
            try:
                result = await asyncio.wait_for(
                    trace_tool_execution(
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        operation=lambda: (
                            self.executor.execute(
                                tool_name=tool_name,
                                arguments=arguments,
                            )
                        ),
                    ),
                    timeout=max(0.001, timeout),
                )
            except asyncio.TimeoutError:
                result = error_result(
                    "EXECUTION_TIMEOUT",
                    "Agent execution time limit reached.",
                )
                status = "failed"

        # -----------------------------------
        # Update State
        # -----------------------------------

        step_count += 1

        # Tool result message
        tool_message = ToolMessage(
            content=json.dumps(
                result,
                ensure_ascii=False,
                default=str,
            ),
            tool_call_id=tool_call_id,
            name=tool_name,
        )

        # Execution history
        history = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
        }

        return {
            "messages": [tool_message],
            "tool_history": [history],
            "step_count": step_count,
            "status": status,
            "pending_approval": None,
        }

    # -----------------------------------
    # Router: After Tools
    # -----------------------------------

    def route_after_tools(
        self,
        state: AgentState,
    ):

        if state["status"] != "running":
            return END

        return "call_llm"

    # -----------------------------------
    # Build LangGraph
    # -----------------------------------

    def build_graph(self):

        builder = StateGraph(AgentState)

        builder.add_node(
            "initialize_execution",
            self.initialize_execution,
        )

        builder.add_node(
            "call_llm",
            self.call_llm,
        )

        builder.add_node(
            "execute_tools",
            self.execute_tools,
        )

        builder.add_edge(
            START,
            "initialize_execution",
        )

        builder.add_edge(
            "initialize_execution",
            "call_llm",
        )

        builder.add_conditional_edges(
            "call_llm",
            self.route_after_llm,
        )

        builder.add_conditional_edges(
            "execute_tools",
            self.route_after_tools,
        )

        return builder.compile(
            checkpointer=self.checkpointer
        )
