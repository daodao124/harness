
import os
from functools import lru_cache
from pathlib import Path
from pymilvus import MilvusClient
from harness.retrieval.model import (
    KnowledgeMatch,
    KnowledgeBaseResult,
)


COLLECTION_NAME = "payment_runbooks"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_DIMENSION = 384


def get_milvus_client():
  

    # Default: Milvus Lite stored locally
    project_root = Path(__file__).resolve().parents[2]
    default_path = project_root / "data" / "payment_kb.db"

    uri = os.getenv("MILVUS_URI")

    if not uri:
        default_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        uri = str(default_path)

    token = os.getenv("MILVUS_TOKEN")

    if token:
        return MilvusClient(uri=uri, token=token)

    return MilvusClient(uri=uri)


@lru_cache(maxsize=1)
def get_embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def search_milvus(
    query: str,
    error_code: str | None = None,
    limit: int = 5,
) -> KnowledgeBaseResult:

    model = get_embedding_model()

    search_text = f"{error_code or ''} {query}".strip()

    query_vector = model.encode(
        search_text,
        normalize_embeddings=True,
    ).tolist()

    client = get_milvus_client()

    try:
        if not client.has_collection(COLLECTION_NAME):
            raise RuntimeError(
                "Milvus collection not found. "
                "Run the index_kb script first."
            )

        results = client.search(
            collection_name=COLLECTION_NAME,
            data=[query_vector],
            limit=limit,
            output_fields=[
                "title",
                "source",
                "text",
                "error_code",
            ],
            search_params={
                "metric_type": "COSINE",
                "params": {},
            },
        )

        matches = []

        for hit in results[0]:
            entity = hit["entity"]

            matches.append(
                KnowledgeMatch(
                    title=entity["title"],
                    source=entity["source"],
                    content=entity["text"],
                    error_code=entity.get("error_code") or None,
                    score=float(hit["distance"]),
                    score_type="cosine",
                )
            )

        return KnowledgeBaseResult(
            query=query,
            backend="milvus",
            matches=matches,
        )

    finally:
        client.close()
