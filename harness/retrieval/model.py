from typing import Literal
from pydantic import BaseModel, Field


class KnowledgeMatch(BaseModel):
    title: str
    source: str
    content: str
    error_code: str | None = None
    score: float
    score_type: Literal["keyword", "cosine"]


class KnowledgeBaseResult(BaseModel):
    query: str
    backend: Literal["local", "milvus"]
    matches: list[KnowledgeMatch] = Field(default_factory=list)