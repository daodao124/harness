
from harness.retrieval.local import search_local
from harness.retrieval.milvus import search_milvus


def search_knowledge_base(
    query: str,
    error_code: str | None = None,
    related_error_codes: list[str] | None = None,
    limit: int = 5,
):
    if not query.strip():
        raise ValueError("Query cannot be empty")

    if not 1 <= limit <= 20:
        raise ValueError("Limit must be between 1 and 20")

    related_error_codes = related_error_codes or []

    distinct_codes = {
        code.upper()
        for code in [error_code, *related_error_codes]
        if code
    }

    # Case 1: Multiple errors requiring semantic retrieval
    if len(distinct_codes) > 1:
        return search_milvus(
            query=query + " " + " ".join(sorted(distinct_codes)),
            limit=limit,
        )

    # Case 2: Try local retrieval first
    local_result = search_local(
        query=query,
        error_code=error_code,
        limit=limit,
    )

    # Case 3: Check exact error code match
    if error_code:
        exact_matches = [
            match
            for match in local_result.matches
            if match.error_code
            and match.error_code.upper() == error_code.upper()
        ]

        if exact_matches:
            return local_result.model_copy(
                update={"matches": exact_matches}
            )

    # Case 4: No exact match -> Semantic search
    return search_milvus(
        query=query,
        error_code=error_code,
        limit=limit,
    )
