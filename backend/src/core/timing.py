"""Per-request stage timings: where the time of one search went.

A request opens a timing scope (``timed_request``); code on its path wraps work in
``stage("asr")`` and the durations add up per stage name. Starlette copies the context into the
threadpool that runs the sync endpoints, so stages recorded there land in the same scope.
Outside a scope (tests, scripts) ``stage`` costs one context lookup and records nothing.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_stages: ContextVar[dict[str, float] | None] = ContextVar("request_stages", default=None)


@contextmanager
def timed_request() -> Iterator[dict[str, float]]:
    """Stage name -> milliseconds, filled while the block runs."""
    stages: dict[str, float] = {}
    token = _stages.set(stages)
    try:
        yield stages
    finally:
        _stages.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    stages = _stages.get()
    if stages is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        stages[name] = stages.get(name, 0.0) + (time.perf_counter() - started) * 1000


def format_stages(stages: dict[str, float]) -> str:
    return " ".join(f"{name}={ms:.0f}ms" for name, ms in stages.items())
