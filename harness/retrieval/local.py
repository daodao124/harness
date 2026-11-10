
import re

from harness.retrieval.model import (
    KnowledgeMatch,
    KnowledgeBaseResult,
)

### Load document 

import re
from dataclasses import dataclass
from pathlib import Path
from rank_bm25 import BM25Okapi


KB_DIR = (
    Path(__file__).resolve().parents[1]
    / "knowledge_base"
)


@dataclass
class DocumentChunk:
    title: str
    source: str
    content: str
    error_code: str | None


def load_document_chunks() -> list[DocumentChunk]:
    """ Chunk base on format of knowlegdbe base
    """

    if not KB_DIR.is_dir():
        raise FileNotFoundError(
            f"Knowledge Base folder not found: {KB_DIR}"
        )

    chunks = []

    for path in sorted(KB_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")

        if not content.strip():
            continue

        # Extract error code from document metadata
        match = re.search(
            r"(?im)^Error code:\s*([A-Z0-9_]+)",
            content,
        )

        error_code = match.group(1) if match else None

        # Split document into chunks by ## headings
        sections = re.split(r"(?m)^##[ \t]+([^\r\n]+)\r?\n",content,)

        introduction = sections[0].strip()

        if len(sections) == 1:
            chunks.append(
                DocumentChunk(
                    title=path.stem,
                    source=path.name,
                    content=content.strip(),
                    error_code=error_code,
                )
            )
            continue

        for i in range(1, len(sections), 2):
            heading = sections[i].strip()
            body = sections[i + 1].strip()

            if not body:
                continue

            chunk_content = (f"{introduction}\n\n"f"## {heading}\n{body}")

            chunks.append(
                DocumentChunk(
                    title=f"{path.stem} / {heading}",
                    source=path.name,
                    content=chunk_content,
                    error_code=error_code,
                )
            )

    return chunks

#### Processing document

def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower())) 

def extract_error_code(query: str) -> str | None:
    """Extract uppercase error code from query."""

    match = re.search(
        r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b",
        query,
    )

    return match.group(0) if match else None


def search_local(
    query: str,
    error_code: str | None = None,
    limit: int = 5,) -> KnowledgeBaseResult:

    # 1. Validate arguments
    if not query.strip():
        raise ValueError("Query cannot be empty")

    if not 1 <= limit <= 20:
        raise ValueError("Limit must be between 1 and 20")

    # 2. Load knowledge base documents
    chunks = load_document_chunks()

    if not chunks:
        return KnowledgeBaseResult(
            query=query,
            backend="local",
            matches=[],
        )

    # 3. Prepare document corpus
    corpus = [
        tokenize(
            f"{chunk.title} {chunk.content}"
        )
        for chunk in chunks
    ]

    # 4. Build BM25 index
    bm25 = BM25Okapi(corpus)

    # 5. Prepare query
    detected_code = error_code or extract_error_code(query)

    query_text = f"{detected_code or ''} {query}"
    query_tokens = tokenize(query_text)

    # 6. Calculate BM25 scores
    bm25_scores = bm25.get_scores(query_tokens)

    matches = []

    for chunk, tokens, bm25_score in zip(
        chunks, corpus, bm25_scores
    ):
        score = max(0.0, float(bm25_score))

        # 7. Exact error_code matching
        exact_match = (
            detected_code is not None
            and chunk.error_code is not None
            and chunk.error_code.upper() == detected_code.upper()
        )

        if exact_match:
            score += 10.0

        # Small tie-breaker / fallback for tiny corpora
        keyword_overlap = len(
            set(query_tokens) & set(tokens)
        )

        score += 0.01 * keyword_overlap

        if score <= 0:
            continue

        # 8. Build result
        matches.append(
            KnowledgeMatch(
                title=chunk.title,
                source=chunk.source,
                content=chunk.content,
                error_code=chunk.error_code,
                score=round(score, 4),
                score_type="keyword",
            )
        )

    # 9. Rank documents
    matches.sort(
        key=lambda item: (
            -item.score,
            item.source,
            item.title,
        )
    )

    # 10. Return top-k matches
    return KnowledgeBaseResult(
        query=query,
        backend="local",
        matches=matches[:limit],
    )