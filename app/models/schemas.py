from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator
Status = Literal["healthy", "degraded", "down"]
FaultType = Literal["database_connection_error", "service_unavailable", "high_latency", "intermittent_failure"]
class FailureRequest(BaseModel):
    status: Status
    reason: str = Field(min_length=1, max_length=500)
class PaymentRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0, le=1000000)
    currency: str = Field(min_length=3, max_length=3)
    @field_validator("currency")
    @classmethod
    def supported_currency(cls, value: str) -> str:
        value = value.upper()
        if value not in {"USD", "EUR", "GBP", "CAD", "AUD", "JPY"}:
            raise ValueError("Unsupported currency")
        return value
class FaultRequest(BaseModel):
    fault_type: FaultType
    duration_seconds: int = Field(gt=0, le=3600)
class ServiceStatus(BaseModel):
    service_name: str = "payment-service"
    status: Status
    last_updated: datetime
    message: str
