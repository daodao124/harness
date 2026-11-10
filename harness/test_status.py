import asyncio
from harness.tool.service_status import get_service_status


async def main():
    result = await get_service_status("payment-service")
    print(result.model_dump())


if __name__ == "__main__":
    asyncio.run(main())