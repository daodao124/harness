
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from harness.tool.service_status import get_service_status, ServiceStatus
from harness.tool.get_error_log import get_error_logs, ErrorLogsResult
from harness.tool.search_knowledge_base import search_knowledge_base

from harness.retrieval.model import KnowledgeBaseResult
from harness.tool.create_incident import  create_incident, IncidentResult


# ------------------------
# 1. Input Schemas
# ------------------------

class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceStatusArgs(ToolArguments):
    service_name: Literal["payment-service"]


class ErrorLogsArgs(ToolArguments):
    service_name: Literal["payment-service"]
    level: str = "ERROR"
    limit: int = Field(default=20, ge=1, le=100)
    event: str | None = None
    request_id: str | None = None
    error_code: str | None = None

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        allowed = {
            "DEBUG", "INFO", "WARNING",
            "ERROR", "CRITICAL",
        }

        levels = [
            item.strip().upper()
            for item in value.split(",")
        ]

        if any(level not in allowed for level in levels):
            raise ValueError("Invalid log level")

        return ",".join(levels)


class KnowledgeBaseArgs(ToolArguments):
    query: str = Field(min_length=1, max_length=1000)
    error_code: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


class IncidentArgs(ToolArguments):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10)
    severity: Literal[
        "low", "medium", "high", "critical"
    ]


# ------------------------
# 2. Tool Specification
# ------------------------

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    function: Callable[..., Any]
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    timeout_seconds: float = 10.0
    requires_approval: bool = False


# ------------------------
# 3. Tool Registry
# ------------------------

TOOL_REGISTRY: dict[str, ToolSpec] = {
    "get_service_status": ToolSpec(
        name="get_service_status",
        description="Get the current payment service status.",
        function=get_service_status,
        input_schema=ServiceStatusArgs,
        output_schema=ServiceStatus,
        timeout_seconds=7,
    ),

    "get_error_logs": ToolSpec(
        name="get_error_logs",
        description="Retrieve and filter payment service error logs.",
        function=get_error_logs,
        input_schema=ErrorLogsArgs,
        output_schema=ErrorLogsResult,
        timeout_seconds=7,
    ),

    "search_knowledge_base": ToolSpec(
        name="search_knowledge_base",
        description=(
            "Find troubleshooting guidance for an error "
            "using the configured knowledge retrieval backend."
        ),
        function=search_knowledge_base,
        input_schema=KnowledgeBaseArgs,
        output_schema=KnowledgeBaseResult,
        timeout_seconds=30,
    ),

    "create_incident": ToolSpec(
        name="create_incident",
        description="Create an operations incident.",
        function=create_incident,
        input_schema=IncidentArgs,
        output_schema=IncidentResult,
        timeout_seconds=10,
        requires_approval=True,
    ),
}


def get_tool(name: str) -> ToolSpec | None:
    return TOOL_REGISTRY.get(name)


def get_tool_definitions() -> list[dict]:
    """Tool definitions for the future LLM integration."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema.model_json_schema(),
        }
        for tool in TOOL_REGISTRY.values()
    ]
