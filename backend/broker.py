import os
from pathlib import Path

from dotenv import load_dotenv
from taskiq_redis import RedisStreamBroker

load_dotenv(Path(__file__).resolve().parent / ".env")

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("REDIS_URL must be set to your Upstash Redis connection URL.")

broker = RedisStreamBroker(url=redis_url)
