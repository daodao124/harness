
import argparse
import os

from harness.tool.search_knowledge_base import search_knowledge_base


def main():
    parser = argparse.ArgumentParser(
        description="Test Knowledge Base Search"
    )

    parser.add_argument(
        "--query",
        type=str,
        default="Unable to connect to payment database",
        help="Search query",
    )

    parser.add_argument(
        "--error-code",
        type=str,
        default="DATABASE_CONNECTION_ERROR",
        help="Error code from payment logs",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of results",
    )

    args = parser.parse_args()

    backend = os.getenv("KB_BACKEND", "local")

    print("=" * 60)
    print("KNOWLEDGE BASE SEARCH TEST")
    print("=" * 60)

    print(f"Backend    : {backend}")
    print(f"Query      : {args.query}")
    print(f"Error Code : {args.error_code}")
    print(f"Limit      : {args.limit}")

    print("-" * 60)

    # Call Knowledge Base tool
    result = search_knowledge_base(
        query=args.query,
        error_code=args.error_code,
        limit=args.limit,
    )

    print(f"Results found: {len(result.matches)}")

    if not result.matches:
        print("No matching knowledge found.")
        return

    for index, match in enumerate(result.matches, start=1):
        print(f"\n{'=' * 20} MATCH {index} {'=' * 20}")

        print(f"Title      : {match.title}")
        print(f"Source     : {match.source}")
        print(f"Error Code : {match.error_code}")
        print(f"Score      : {match.score}")
        print(f"Score Type : {match.score_type}")

        print("\nContent:")
        print(match.content)

    print("\n" + "=" * 60)
    print("SEARCH COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()
