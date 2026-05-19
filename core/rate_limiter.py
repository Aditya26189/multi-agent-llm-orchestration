# core/rate_limiter.py
import asyncio
import time
import os
from redis.asyncio import Redis, ConnectionPool

_lock = asyncio.Lock()
_timestamps: list = []
_CALLS_PER_MINUTE = 12  # safe buffer under 15 RPM Gemini free tier
_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_KEY = "gemini_rate_limit_ts"

async def wait(model_name: str = "default") -> None:
    global _timestamps
    
    # Try Redis first for distributed rate limiting across Celery worker processes
    pool = None
    client = None
    try:
        pool = ConnectionPool.from_url(_REDIS_URL, socket_timeout=2.0)
        client = Redis(connection_pool=pool)
        while True:
            now = time.time()
            one_minute_ago = now - 60.0
            
            # Clean up old timestamps
            await client.zremrangebyscore(_KEY, 0, one_minute_ago)
            
            # Count requests in the last 60 seconds
            count = await client.zcard(_KEY)
            
            if count < _CALLS_PER_MINUTE:
                # Add current request timestamp
                await client.zadd(_KEY, {str(now): now})
                break
                
            # Quota full, calculate wait time based on oldest timestamp
            oldest = await client.zrange(_KEY, 0, 0, withscores=True)
            if oldest:
                oldest_ts = oldest[0][1]
                sleep_time = max(1.0, 60.0 - (now - oldest_ts) + 0.5)
            else:
                sleep_time = 2.0
                
            await asyncio.sleep(sleep_time)
        return
    except Exception as e:
        # Fall back to in-memory rate limiting if Redis is unavailable
        pass
    finally:
        if client:
            try:
                await client.aclose()
            except Exception:
                pass
        if pool:
            try:
                await pool.disconnect()
            except Exception:
                pass

    # In-memory fallback
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
            is_transient = any(
                x in str(e).lower()
                for x in ["429", "resource_exhausted", "quota", "503", "unavailable", "overloaded"]
            )
            if not is_transient or attempt >= max_retries:
                raise
            sleep_time = (2 ** attempt) * 5
            print(f"  [rate_limiter] transient error or quota hit, sleeping {sleep_time}s: {e}")
            await asyncio.sleep(sleep_time)
    raise last_error or RuntimeError("call_with_backoff: all retries exhausted")