
import asyncio
import json

from harness.core.executor import ToolExecutor
from harness.core.registry import TOOL_REGISTRY


async def main():

    executor = ToolExecutor()

    # 1. Show registered tools
    print("\n========== TOOL REGISTRY ==========")

    for name, tool in TOOL_REGISTRY.items():
        print(
            f"Tool: {name} | "
            f"Timeout: {tool.timeout_seconds}s | "
            f"Approval: {tool.requires_approval}"
        )

    # 2. Define test cases
    test_cases = [
        {
            "name": "Get Service Status",
            "tool": "get_service_status",
            "arguments": {
                "service_name": "payment-service"
            },
            "expected": "SUCCESS",
        },
        {
            "name": "Get Error Logs",
            "tool": "get_error_logs",
            "arguments": {
                "service_name": "payment-service",
                "level": "ERROR",
                "limit": 5,
            },
            "expected": "SUCCESS",
        },
        {
            "name": "Search Knowledge Base",
            "tool": "search_knowledge_base",
            "arguments": {
                "query": "Unable to connect to payment database",
                "error_code": "DATABASE_CONNECTION_ERROR",
                "limit": 3,
            },
            "expected": "SUCCESS",
        },
        {
            "name": "Unknown Tool",
            "tool": "delete_database",
            "arguments": {},
            "expected": "UNKNOWN_TOOL",
        },
        {
            "name": "Invalid Arguments",
            "tool": "get_service_status",
            "arguments": {
                "service_name": "unknown-service"
            },
            "expected": "INVALID_ARGUMENTS",
        },
        {
            "name": "Create Incident Without Approval",
            "tool": "create_incident",
            "arguments": {
                "title": "Payment Service Down",
                "description": (
                    "Payment service is unavailable due "
                    "to database connection errors."
                ),
                "severity": "high",
            },
            "expected": "APPROVAL_REQUIRED",
        },
    ]

    # 3. Execute test cases
    passed = 0
    failed = 0

    for index, case in enumerate(test_cases, start=1):

        print(f"\n========== TEST {index} ==========")
        print(f"Name: {case['name']}")
        print(f"Tool: {case['tool']}")
        print(f"Arguments: {case['arguments']}")

        result = await executor.execute(
            tool_name=case["tool"],
            arguments=case["arguments"],
        )

        print("\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # 4. Validate expected result
        if case["expected"] == "SUCCESS":
            success = result["ok"] is True
        else:
            success = (
                result["ok"] is False
                and result["error"] is not None
                and result["error"]["code"] == case["expected"]
            )

        if success:
            passed += 1
            print("\n[PASS]")
        else:
            failed += 1
            print("\n[FAIL]")
            print(f"Expected: {case['expected']}")

    # 5. Summary
    print("\n========== TEST SUMMARY ==========")
    print(f"Total : {len(test_cases)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
