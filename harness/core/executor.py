
import asyncio
import inspect
import json
import logging
import secrets
import time
import httpx

from pydantic import ValidationError

from harness.core.registry import get_tool
from harness.tool.create_incident import IdempotencyConflictError


logger = logging.getLogger(__name__)


class ToolExecutor:

    def __init__(self):
        self._approval_grants = {}

    def issue_approval(
        self,
        tool_name: str,
        arguments: dict,
    ) -> str:
        """Issue a one-time grant after trusted user approval."""

        tool = get_tool(tool_name)

        if tool is None or not tool.requires_approval:
            raise ValueError("Tool does not require approval")

        validated = tool.input_schema.model_validate(arguments)

        canonical_args = json.dumps(
            validated.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )

        token = secrets.token_urlsafe(32)

        self._approval_grants[token] = (
            tool_name,
            canonical_args,
        )

        return token

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        *,
        approval_token: str | None = None,
        execution_id: str | None = None,
    ) -> dict:

        start = time.perf_counter()

        def failure(code: str, message: str) -> dict:
            return {
                "ok": False,
                "tool": tool_name,
                "data": None,
                "error": {
                    "code": code,
                    "message": message,
                },
                "duration_ms": round(
                    (time.perf_counter() - start) * 1000,
                    2,
                ),
            }

        # 1. Find tool
        tool = get_tool(tool_name)

        if tool is None:
            return failure(
                "UNKNOWN_TOOL",
                "Tool is not registered.",
            )

        # 2. Validate LLM arguments
        try:
            validated = tool.input_schema.model_validate(arguments)
        except (ValidationError, TypeError, ValueError):
            return failure(
                "INVALID_ARGUMENTS",
                "Invalid tool arguments.",
            )

        params = validated.model_dump()

        # 3. Enforce approval for write tools
        if tool.requires_approval:

            canonical_args = json.dumps(
                validated.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )

            expected = (tool_name, canonical_args)

            granted = self._approval_grants.pop(
                approval_token, None
            ) if approval_token else None

            if granted != expected:
                return failure(
                    "APPROVAL_REQUIRED",
                    "Human approval is required.",
                )

            # Only trusted Harness may supply execution_id
            if tool_name == "create_incident":

                if (
                    not isinstance(execution_id, str)
                    or not execution_id.strip()
                    or len(execution_id) > 256
                ):
                    return failure(
                        "INVALID_EXECUTION_ID",
                        "Valid execution ID is required.",
                    )

                params["idempotency_key"] = execution_id

        # 4. Execute
        async def invoke():

            if inspect.iscoroutinefunction(tool.function):
                return await tool.function(**params)

            return await asyncio.to_thread(
                tool.function,
                **params,
            )

        try:
            raw_result = await asyncio.wait_for(
                invoke(),
                timeout=tool.timeout_seconds,
            )

        except asyncio.TimeoutError:
            return failure(
                "TOOL_TIMEOUT",
                "Tool execution timed out.",
            )

        except IdempotencyConflictError:
            return failure(
                "IDEMPOTENCY_CONFLICT",
                "Execution ID was used with different incident data.",
            )

        except Exception:
            logger.exception(
                "Tool execution failed: %s",
                tool_name,
            )
            return failure(
                "TOOL_EXECUTION_FAILED",
                "Tool execution failed.",
            )

        # 5. Validate output
        try:
            output = tool.output_schema.model_validate(
                raw_result
            )
        except (ValidationError, TypeError, ValueError):
            return failure(
                "INVALID_TOOL_OUTPUT",
                "Invalid tool output.",
            )

        return {
            "ok": True,
            "tool": tool_name,
            "data": output.model_dump(mode="json"),
            "error": None,
            "duration_ms": round(
                (time.perf_counter() - start) * 1000,
                2,
            ),
        }
