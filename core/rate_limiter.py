# core/rate_limiter.py
import asyncio
import time

_timestamps: list = []
_CALLS_PER_MINUTE = 12

async def wait(model_name: str = "default") -> None:
    global _timestamps
    now = time.monotonic()
    _timestamps = [t for t in _timestamps if now - t < 60.0]
    if len(_timestamps) >= _CALLS_PER_MINUTE:
        sleep_for = 60.0 - (now - _timestamps[0]) + 0.5
        await asyncio.sleep(sleep_for)
    _timestamps.append(time.monotonic())

def wait_sync(seconds: float = 4.1) -> None:
    time.sleep(seconds)

async def call_with_backoff(fn, *args, max_retries: int = 2, **kwargs):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            await wait()
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            last_error = e
            is_rate_limit = any(x in str(e).lower() for x in ["429", "resource_exhausted", "quota"])
            if not is_rate_limit or attempt >= max_retries:
                raise
            await asyncio.sleep((2 ** attempt) * 2)
    raise last_error
