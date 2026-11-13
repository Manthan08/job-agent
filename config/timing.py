"""Lightweight per-stage timing.

Turns the "why is this slow?" guess into measured fact. Every heavy stage
(LLM call, PDF render, full tailor/coach run) is wrapped in `timed(...)`, which
logs the wall-clock seconds when the block exits.

Output goes to stdout (visible in HF Spaces container logs thanks to
PYTHONUNBUFFERED=1) and to the `job_agent.timing` logger. Silence it by setting
JOB_AGENT_TIMING=0 in the environment.

Usage:
    from config.timing import timed
    with timed("tailor.keyword_coverage"):
        report = analyze_keyword_coverage(...)
"""

import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger("job_agent.timing")


def _enabled() -> bool:
    return os.getenv("JOB_AGENT_TIMING", "1").strip().lower() not in {"0", "false", "no", "off"}


@contextmanager
def timed(label: str):
    """Time a block and log its duration when it exits (even on exception)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        if _enabled():
            elapsed = time.perf_counter() - start
            logger.info("[timing] %s: %.2fs", label, elapsed)
            print(f"[timing] {label}: {elapsed:.2f}s", flush=True)
