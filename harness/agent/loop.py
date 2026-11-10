
import json
import logging
import os

from langchain_openai import ChatOpenAI
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

    # Trace every execution attempt.
    # LangGraph retries this task on transient errors.
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
        checkpointer=None,
    ):

        if max_steps < 1:
            raise ValueError(
                "max_steps must be positive"
            )

        self.max_steps = max_steps

        # Initialize LLM
        self.llm = (
            llm
            if llm is not None
            else ChatOpenAI(
                model=model or os.getenv(
                    "OPENAI_MODEL",
                    "gpt-4.1-mini",
                ),
                temperature=0,
                timeout=30,
                max_retries=1,
            )
        )

        # Bind tool definitions
        self.llm_with_tools = self.llm.bind_tools(
            get_tool_definitions(),
            parallel_tool_calls=False,
        )

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

    async def call_llm(
        self,
        state: AgentState,
    ) -> dict:

        if state["status"] == "waiting_approval":
            return {}

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
            response = await (
                self.llm_with_tools.ainvoke(messages)
            )

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
                            result = await trace_tool_execution(
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
                            )

        # -----------------------------------
        # Read Tools + Retry + Tracing
        # -----------------------------------

        elif tool_name in READ_TOOLS:

            try:
                result = await execute_read_task(
                    tool_name,
                    arguments,
                    tool_call_id,
                )

            except RetryableToolError as exc:

                result = error_result(
                    exc.code,
                    "Retry attempts exhausted.",
                )

        # -----------------------------------
        # Unknown or Other Tools
        # -----------------------------------

        else:

            result = await trace_tool_execution(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                operation=lambda: (
                    self.executor.execute(
                        tool_name=tool_name,
                        arguments=arguments,
                    )
                ),
            )

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
            "call_llm",
            self.call_llm,
        )

        builder.add_node(
            "execute_tools",
            self.execute_tools,
        )

        builder.add_edge(
            START,
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
