# core/rate_limiter.py
import asyncio
import time

_lock = asyncio.Lock()
_timestamps: list = []
_CALLS_PER_MINUTE = 12  # safe buffer under 15 RPM Gemini free tier

async def wait(model_name: str = "default") -> None:
    global _timestamps
    async with _lock:
        now = time.monotonic()
        _timestamps = [t for t in _timestamps if now - t < 60.0]
        if len(_timestamps) >= _CALLS_PER_MINUTE:
            sleep_for = 60.0 - (now - _timestamps[0]) + 1.0
            _timestamps.append(time.monotonic())
        else:
            sleep_for = 0
            _timestamps.append(time.monotonic())

    if sleep_for > 0:
        await asyncio.sleep(sleep_for)

def wait_sync(seconds: float = 6.0) -> None:
    time.sleep(seconds)

async def call_with_backoff(fn, *args, max_retries: int = 3, **kwargs):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            await wait()
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            last_error = e
            is_rate_limit = any(
                x in str(e).lower()
                for x in ["429", "resource_exhausted", "quota"]
            )
            if not is_rate_limit or attempt >= max_retries:
                raise
            sleep_time = (2 ** attempt) * 5
            print(f"  [rate_limiter] quota hit, sleeping {sleep_time}s")
            await asyncio.sleep(sleep_time)
    raise last_error or RuntimeError("call_with_backoff: all retries exhausted")