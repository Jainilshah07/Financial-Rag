"""Gemini embeddings with retry on free-tier rate limits."""

import time
from functools import cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from financial_rag.config import settings
from financial_rag.db import EMBEDDING_DIM

MODEL_KEY = f"gemini-embedding-001:{EMBEDDING_DIM}"  # stored in embeddings.model
BATCH_SIZE = 50


@cache
def _client() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=settings.gemini_api_key,
                                        output_dimensionality=EMBEDDING_DIM)


def _retry(fn, arg):
    for attempt in range(6):
        try:
            return fn(arg)
        except Exception as e:
            if attempt == 5 or not any(s in str(e) for s in ("429", "RESOURCE_EXHAUSTED")):
                raise
            time.sleep(15 * (attempt + 1))


def embed_documents(texts: list[str]) -> list[list[float]]:
    """One API call; callers batch by BATCH_SIZE."""
    return _retry(_client().embed_documents, texts)


@cache  # repeated questions (e.g. one evaluation across chunkers) are embedded once
def embed_query(text: str) -> list[float]:
    return _retry(_client().embed_query, text)
