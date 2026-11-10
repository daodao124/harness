
import asyncio

from typing import Literal
from pydantic import BaseModel, ConfigDict, ValidationError

from harness.tool.service_status import get_service_status, ServiceStatus

class GetStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_name: Literal["payment-service"]


class ToolExecutor:

    async def execute(self,
                      tool_name: str,
                       arguments: dict) -> dict:

        # 1. Validate tool name
        if tool_name != "get_service_status":
            return {
                "ok": False,
                "error": "UNKNOWN_TOOL"
            }

        # 2. Validate input
        try:
            validated = GetStatusInput.model_validate(
                arguments
            )
        except ValidationError as exc:
            return {
                "ok": False,
                "error": "INVALID_ARGUMENTS",
                "details": exc.errors(
                    include_url=False,
                    include_input=False
                )
            }

        # 3. Execute tool with timeout
        try:
            result = await asyncio.wait_for(
                get_service_status(
                    validated.service_name
                ),
                timeout=7
            )

            # 4. Validate output
            validated_output = ServiceStatus.model_validate(
                result
            )

            return {
                "ok": True,
                "tool": tool_name,
                "data": validated_output.model_dump()
            }

        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": "TOOL_TIMEOUT"
            }

        except ValidationError:
            return {
                "ok": False,
                "error": "INVALID_TOOL_OUTPUT"
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": "TOOL_EXECUTION_FAILED",
                "details": str(exc)
            }
