"""Tokenisation shared by the local retrieval adapters.

The embedding model and the reranker have to agree on what a term is, otherwise a
query-coverage score would not be comparable with a similarity score computed over the
same text.
"""

from __future__ import annotations

import re

_TERM = re.compile(r"[a-z0-9]+")


def terms(text: str) -> list[str]:
    """Split text into lowercase alphanumeric terms, in the order they appear."""
    return _TERM.findall(text.lower())
