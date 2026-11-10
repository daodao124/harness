
from harness.retrieval.local import search_local


def main():
    query = "Unable to connect to payment database"
    error_code = "DATABASE_CONNECTION_ERROR"

    result = search_local(
        query=query,
        error_code=error_code,
        limit=5,
    )

    print("=== LOCAL BM25 SEARCH ===")
    print(f"Query: {result.query}")
    print(f"Backend: {result.backend}")
    print(f"Total matches: {len(result.matches)}")

    for i, match in enumerate(result.matches, start=1):
        print(f"\n--- MATCH {i} ---")
        print(f"Title: {match.title}")
        print(f"Source: {match.source}")
        print(f"Error Code: {match.error_code}")
        print(f"Score: {match.score}")
        print(f"Content:\n{match.content}")


if __name__ == "__main__":
    main()
