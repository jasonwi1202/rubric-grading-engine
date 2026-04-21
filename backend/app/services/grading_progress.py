"""Redis-based grading batch progress tracking.

Each assignment's batch progress is stored as a Redis Hash so that
``GET /assignments/{id}/grading-status`` can respond entirely from Redis
with zero database queries for the progress counters and per-essay status.

Redis key format: ``grading_progress:{assignment_id}``

Hash fields:
  ``total``              — total essays enqueued in this batch (integer string)
  ``complete``           — essays that finished successfully (integer string)
  ``failed``             — essays that exhausted all retries (integer string)
  ``s:{essay_id}``       — per-essay status: ``queued`` | ``grading`` |
                           ``complete`` | ``failed``
  ``n:{essay_id}``       — student display name (empty string when
                           the essay has no assigned student)
  ``e:{essay_id}``       — error code string (empty string when no error)

TTL: ``settings.redis_grading_ttl_seconds`` (default 3 600 s / 1 hour).
The TTL is refreshed on every write so active batches do not expire.

Security:
- Student display names are stored in the cache.  They are never logged;
  only entity IDs appear in log output.
- Data lives entirely within server-side infrastructure (Redis).  It is
  accessible only to authenticated requests through the API.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis

from app.config import settings

# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX = "grading_progress"


def grading_progress_key(assignment_id: uuid.UUID) -> str:
    """Return the Redis Hash key for an assignment's batch progress."""
    return f"{_KEY_PREFIX}:{assignment_id}"


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


async def initialize_progress(
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    essays: list[tuple[uuid.UUID, str | None]],
) -> None:
    """Initialise the progress hash for a new batch.

    Overwrites any previous hash under the same key.  Call once per batch
    trigger — not per retry (use ``reset_essay_for_retry`` for retries).

    Args:
        redis: Async Redis client (``decode_responses=True``).
        assignment_id: The assignment being graded.
        essays: Sequence of ``(essay_id, student_name)`` pairs.  Pass
            ``None`` for *student_name* when the essay has no student.
    """
    key = grading_progress_key(assignment_id)
    mapping: dict[str, str | bytes | float | int] = {
        "total": str(len(essays)),
        "complete": "0",
        "failed": "0",
    }
    for essay_id, student_name in essays:
        mapping[f"s:{essay_id}"] = "queued"
        mapping[f"n:{essay_id}"] = student_name or ""
        mapping[f"e:{essay_id}"] = ""

    pipe = redis.pipeline()
    pipe.delete(key)
    pipe.hset(key, mapping=mapping)  # type: ignore[arg-type]
    pipe.expire(key, settings.redis_grading_ttl_seconds)
    await pipe.execute()


async def mark_essay_grading(
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    essay_id: uuid.UUID,
) -> None:
    """Update a per-essay status to ``grading`` when the Celery task starts."""
    key = grading_progress_key(assignment_id)
    pipe = redis.pipeline()
    pipe.hset(key, f"s:{essay_id}", "grading")
    pipe.expire(key, settings.redis_grading_ttl_seconds)
    await pipe.execute()


async def mark_essay_complete(
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    essay_id: uuid.UUID,
) -> dict[str, int]:
    """Mark an essay as successfully graded; return updated batch counters.

    Idempotent: if the essay was already marked ``complete`` (e.g. due to a
    Celery at-least-once re-delivery), the ``complete`` counter is **not**
    incremented a second time.

    Returns:
        Dict with ``total``, ``complete``, ``failed`` as integers.
        All values are 0 if the key has expired.
    """
    _MARK_COMPLETE_SCRIPT = """
local total = redis.call('HGET', KEYS[1], 'total')
if not total then
    -- Hash not initialised or has expired; treat as a no-op and return zeros.
    return {false, false, false}
end
local prev = redis.call('HGET', KEYS[1], ARGV[1])
if prev == 'complete' then
    -- Already terminal; counter must not be inflated on re-delivery.
else
    redis.call('HSET', KEYS[1], ARGV[1], 'complete')
    if prev ~= false then
        -- Field exists with a different (non-terminal) value: safe to increment.
        redis.call('HINCRBY', KEYS[1], 'complete', 1)
    end
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return redis.call('HMGET', KEYS[1], 'total', 'complete', 'failed')
"""
    key = grading_progress_key(assignment_id)
    result = await redis.eval(  # type: ignore[no-untyped-call]
        _MARK_COMPLETE_SCRIPT,
        1,
        key,
        f"s:{essay_id}",
        str(settings.redis_grading_ttl_seconds),
    )
    total_str, complete_str, failed_str = result
    return {
        "total": int(total_str or 0),
        "complete": int(complete_str or 0),
        "failed": int(failed_str or 0),
    }


async def mark_essay_failed(
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    essay_id: uuid.UUID,
    error_code: str,
) -> dict[str, int]:
    """Mark an essay as permanently failed; return updated batch counters.

    Idempotent: if the essay was already marked ``failed`` (e.g. due to a
    Celery at-least-once re-delivery), the ``failed`` counter is **not**
    incremented a second time.

    Returns:
        Dict with ``total``, ``complete``, ``failed`` as integers.
        All values are 0 if the key has expired.
    """
    _MARK_FAILED_SCRIPT = """
local total = redis.call('HGET', KEYS[1], 'total')
if not total then
    -- Hash not initialised or has expired; treat as a no-op and return zeros.
    return {false, false, false}
end
local prev = redis.call('HGET', KEYS[1], ARGV[1])
if prev == 'failed' then
    -- Already terminal; counter must not be inflated on re-delivery.
else
    redis.call('HSET', KEYS[1], ARGV[1], 'failed')
    redis.call('HSET', KEYS[1], ARGV[2], ARGV[3])
    if prev ~= false then
        -- Field exists with a different (non-terminal) value: safe to increment.
        redis.call('HINCRBY', KEYS[1], 'failed', 1)
    end
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return redis.call('HMGET', KEYS[1], 'total', 'complete', 'failed')
"""
    key = grading_progress_key(assignment_id)
    result = await redis.eval(  # type: ignore[no-untyped-call]
        _MARK_FAILED_SCRIPT,
        1,
        key,
        f"s:{essay_id}",
        f"e:{essay_id}",
        error_code,
        str(settings.redis_grading_ttl_seconds),
    )
    total_str, complete_str, failed_str = result
    return {
        "total": int(total_str or 0),
        "complete": int(complete_str or 0),
        "failed": int(failed_str or 0),
    }


async def reset_essay_for_retry(
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
    essay_id: uuid.UUID,
) -> None:
    """Reset a failed essay to ``queued`` for retry.

    Decrements the ``failed`` counter and clears the error code so that the
    progress snapshot is accurate after the teacher re-enqueues a single
    essay via ``POST /essays/{essayId}/grade/retry``.

    Guard: the decrement only happens when ``s:{essay_id}`` is currently
    ``"failed"``.  If the key is missing or the essay is in any other state
    the operation is a no-op, preventing the counter from going negative.
    """
    _RESET_RETRY_SCRIPT = """
local prev = redis.call('HGET', KEYS[1], ARGV[1])
if prev == 'failed' then
    redis.call('HSET', KEYS[1], ARGV[1], 'queued')
    redis.call('HSET', KEYS[1], ARGV[2], '')
    redis.call('HINCRBY', KEYS[1], 'failed', -1)
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
end
return 1
"""
    key = grading_progress_key(assignment_id)
    await redis.eval(  # type: ignore[no-untyped-call]
        _RESET_RETRY_SCRIPT,
        1,
        key,
        f"s:{essay_id}",
        f"e:{essay_id}",
        str(settings.redis_grading_ttl_seconds),
    )


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


class EssayProgress:
    """Per-essay progress snapshot."""

    __slots__ = ("essay_id", "status", "student_name", "error")

    def __init__(
        self,
        essay_id: uuid.UUID,
        status: str,
        student_name: str | None,
        error: str | None,
    ) -> None:
        self.essay_id = essay_id
        self.status = status
        self.student_name = student_name or None
        self.error = error or None


class BatchProgress:
    """Full progress snapshot for an assignment batch."""

    __slots__ = ("total", "complete", "failed", "essays")

    def __init__(
        self,
        total: int,
        complete: int,
        failed: int,
        essays: list[EssayProgress],
    ) -> None:
        self.total = total
        self.complete = complete
        self.failed = failed
        self.essays = essays


async def get_progress(
    redis: Redis,  # type: ignore[type-arg]
    assignment_id: uuid.UUID,
) -> BatchProgress | None:
    """Read the full progress snapshot from Redis.

    Returns:
        ``BatchProgress`` if the key exists and has data, otherwise ``None``
        (key never initialised or TTL expired).
    """
    key = grading_progress_key(assignment_id)
    data: dict[str, str] = await redis.hgetall(key)
    if not data:
        return None

    total = int(data.get("total", 0))
    complete = int(data.get("complete", 0))
    failed = int(data.get("failed", 0))

    essays: list[EssayProgress] = []
    for field, value in data.items():
        if not field.startswith("s:"):
            continue
        essay_id_str = field[2:]
        try:
            essay_id = uuid.UUID(essay_id_str)
        except ValueError:
            continue
        essays.append(
            EssayProgress(
                essay_id=essay_id,
                status=value,
                student_name=data.get(f"n:{essay_id_str}"),
                error=data.get(f"e:{essay_id_str}"),
            )
        )

    return BatchProgress(total=total, complete=complete, failed=failed, essays=essays)
