
import httpx
from pydantic import BaseModel
from typing import Literal


class ServiceStatus(BaseModel):
    service_name: str
    status: Literal["healthy", "degraded", "down"]
    message: str | None = None


async def get_service_status(
    service_name: str
) -> ServiceStatus:

    if service_name != "payment-service":
        raise ValueError("Unknown service")

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            "http://localhost:8001/status"
        )

        response.raise_for_status()

        return ServiceStatus.model_validate(
            response.json()
        )
