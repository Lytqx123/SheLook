"""Safe bridge between Celery's synchronous workers and async application code.

Celery's prefork pool imports task modules before it forks worker processes.  An
async SQLAlchemy engine created at import time must therefore not retain its
parent process connection pool.  In addition, ``asyncio.run`` creates and
closes an event loop for each synchronous task invocation; an asyncpg
connection left in the pool would be bound to that previous loop.

This module centralises both lifecycle rules for all Celery tasks.
"""

import asyncio
from collections.abc import Awaitable

from celery.signals import worker_process_init

from app.db.session import engine


@worker_process_init.connect
def reset_inherited_async_pool(**_kwargs: object) -> None:
    """Replace connections inherited from Celery's parent process after fork."""
    # ``close=False`` intentionally leaves parent-owned connections alone;
    # the child gets a fresh pool when it first needs one.
    engine.sync_engine.dispose(close=False)


async def _run_and_dispose[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    finally:
        # ``asyncio.run`` closes its loop immediately afterwards.  Disposing
        # while that loop is still alive prevents asyncpg connections from
        # being reused by a later task on a different loop.
        await engine.dispose()


def run_async_task[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    """Run one async Celery task with an event-loop-safe database lifecycle."""
    return asyncio.run(_run_and_dispose(awaitable))
