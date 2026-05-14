"""Finding Aggregator Agent stub — P1."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def aggregate(findings: list[dict]) -> list[dict]:
    """Placeholder: dedup, normalize severity, mark blocking."""
    # TODO: implement dedup + severity normalization in P1
    return findings
