import os
from pathlib import Path

from dotenv import load_dotenv
from taskiq_redis import RedisStreamBroker

load_dotenv(Path(__file__).resolve().parent / ".env")

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("REDIS_URL must be set for API job submission and the extraction worker.")

broker = RedisStreamBroker(
    url=redis_url,
    idle_timeout=int(os.getenv("REDIS_UNACKNOWLEDGED_IDLE_MS", "600000")),
    unacknowledged_lock_timeout=float(
        os.getenv("REDIS_UNACKNOWLEDGED_LOCK_TIMEOUT_SECONDS", "30")
    ),
)
