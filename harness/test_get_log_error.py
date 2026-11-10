
import asyncio

from harness.tool.get_error_log import get_error_logs


async def main():

    # Test 1: Get ERROR logs
    result = await get_error_logs(
        service_name="payment-service",
        level="ERROR",
        limit=20,
    )

    print("=== ALL ERROR LOGS ===")
    print(result.model_dump_json(indent=2))

    # Test 2: Filter by error code
    result = await get_error_logs(
        service_name="payment-service",
        error_code="DATABASE_CONNECTION_ERROR",
    )

    print("=== DATABASE ERRORS ===")
    print(result.model_dump_json(indent=2))

    # Test 3: Multiple log levels
    result = await get_error_logs(
        service_name="payment-service",
        level="ERROR,WARNING",
    )

    print("=== ERROR + WARNING ===")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
