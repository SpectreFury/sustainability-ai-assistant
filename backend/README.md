# Backend

## Local development

Docker is used only for Postgres and Redis. Run the API, extraction worker, and
outbox dispatcher directly from the existing Python environment. Set
`DATABASE_URL` to `postgresql+asyncpg://user:password@localhost:5432/kuki` and
`REDIS_URL` to `redis://localhost:6379/0` in `.env`; also fill in the Cloudinary,
Gemini, and authentication settings.

Start the local dependencies from this directory:

```sh
docker compose up -d --wait postgres redis
```

Apply database migrations once:

```sh
./.venv/bin/alembic upgrade head
```

Then run each process in its own terminal, from this directory:

```sh
./.venv/bin/fastapi run main.py --host 0.0.0.0 --port 8000
```

```sh
./.venv/bin/taskiq worker --workers 1 --max-async-tasks 4 --ack-type when_executed broker:broker workers.extraction
```

```sh
./.venv/bin/python -m workers.dispatcher
```

The API listens on port 8000. Start the frontend separately from `app` with
`npm run dev`. Stop the local database and Redis with `docker compose down`; the
volumes remain in place. Use `docker compose down -v` only when you intend to
delete that local data.

## Recovery settings

- `EXTRACTION_RUN_LEASE_SECONDS`: duration of a worker claim before recovery;
  defaults to 120 seconds.
- `EXTRACTION_RUN_HEARTBEAT_SECONDS`: interval for renewing an active claim;
  defaults to 30 seconds and is capped at half the lease duration.
- `REDIS_UNACKNOWLEDGED_IDLE_MS`: when Taskiq Redis may reclaim an unacknowledged
  message; defaults to 10 minutes.
- `REDIS_UNACKNOWLEDGED_LOCK_TIMEOUT_SECONDS`: expiry for Taskiq Redis's
  unacknowledged-message claim lock; defaults to 30 seconds.
