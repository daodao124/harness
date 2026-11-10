from datetime import datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field


LogLevel = Literal[
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
]



from datetime import datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field


LogLevel = Literal[
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
]


class LogEntry(BaseModel):
    timestamp: datetime
    level: LogLevel
    service: str
    event: str
    message: str

    request_id: str | None = None
    error_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorLogsResult(BaseModel):
    service_name: str
    logs: list[LogEntry] = Field(default_factory=list)


def normalize_levels(level: str) -> str:
    """Validate and normalize comma-separated levels."""

    levels = [item.strip().upper()  for item in level.split(",")]

    allowed = { "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    if not levels or any(item not in allowed for item in levels):
        raise ValueError("Invalid log level")

    return ",".join(levels)


async def get_error_logs(
    service_name: str,
    level: str = "ERROR",
    limit: int = 20,
    event: str | None = None,
    request_id: str | None = None,
    error_code: str | None = None,
) -> ErrorLogsResult:

    # 1. Validate service
    if service_name != "payment-service":
        raise ValueError("Unknown service")

    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")

    # 2. Prepare filters
    params = {
        "level": normalize_levels(level),
        "limit": limit,
    }

    if event:
        params["event"] = event

    if request_id:
        params["request_id"] = request_id

    if error_code:
        params["error_code"] = error_code

    # 3. Call Payment Service API
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            "http://127.0.0.1:8001/logs",
            params=params,
        )
        response.raise_for_status()

    # 4. Parse API response
    payload = response.json()

    if isinstance(payload, list):
        raw_logs = payload
    elif isinstance(payload, dict) and isinstance(
        payload.get("logs"), list
    ):
        raw_logs = payload["logs"]
    else:
        raise ValueError("Unexpected /logs response structure")

    # 5. Validate log entries
    logs = [
        LogEntry.model_validate(log)
        for log in raw_logs
    ]

    return ErrorLogsResult(
        service_name=service_name,
        logs=logs,
    )
