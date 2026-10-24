# Backend

## Local development

Docker is used only for Postgres and Redis. Run the API and extraction worker
directly from the existing Python environment. The API publishes jobs to Redis
after saving their database records. Set
`DATABASE_URL` to `postgresql+asyncpg://user:password@localhost:5432/kuki` and
`REDIS_URL` to `redis://localhost:6379/0` in `.env`; also fill in the Cloudinary,
Gemini, and authentication settings. Select the document fact extraction model
with `DOCUMENT_EXTRACTION_MODEL` and the model used to generate Ask AI and
evaluation answers with `ANSWER_GENERATION_MODEL`.

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
uv run taskiq worker --log-level INFO --workers 1 --max-async-tasks 4 --ack-type when_executed broker:broker workers.extraction
```

The API listens on port 8000. Start the frontend separately from `app` with
`npm run dev`. Stop the local database and Redis with `docker compose down`; the
volumes remain in place. Use `docker compose down -v` only when you intend to
delete that local data.

## Source-backed evaluations

The Evaluations page runs the versioned `kuki-dataset-v4` case pack through the
current extraction, answer, and financial-year workflows. Upload the matching
source files with these exact filenames:

- `Annual Electricity Consumption.xlsx`
- `Adani commercial electricity bill.pdf`
- `BESCOM Commercial Electricity Bill.pdf`
- `form 3 filled.docx.pdf`
- `quality_policy_nestle.pdf`
- `water_bill_invoice.pdf`

Each run pins their file hashes, re-downloads the original bytes, and freshly
extracts each available source once before asking and scoring thirteen
question-answer cases. A separate multi-resource FY case checks coverage and
no-data handling through the Financial-Year Summary service against the
workbook extraction pinned at run creation. Process the workbook successfully
before starting a run so that this FY case can be evaluated. Missing or
incomplete uploads are recorded as blocked, while a fresh extraction failure is
recorded as an error. Answers and verified source locations are saved with the
run without adding evaluation questions to Ask AI answer history. The API
publishes each evaluation directly to Redis, and the extraction worker handles
both evaluation and document-processing tasks.

The case-pack hash, answer and extraction prompt hashes, model names, uploaded
file hashes, fresh extraction outputs, results, and dimension checks are saved
for each run. Extraction facts and generated answers are scored separately. A
pass rate describes this case pack only; it is not a claim of performance on
unseen documents. With all six source files uploaded, a run makes up to six
fresh extraction calls plus up to thirteen answer calls, so it requires the
configured Gemini credentials and incurs the corresponding model usage. The FY
case is blocked when the workbook has no successful persisted extraction at
the time the run starts.

## Redis job recovery

Jobs are published directly to Redis after their database records are saved.
Redis uses AOF persistence in the supplied Compose configuration. Taskiq keeps
unacknowledged jobs in its stream; after a worker restart, Redis can redeliver
them and the worker reclaims queued or expired-running records. Stop the worker
gracefully for normal restarts so active tasks can finish. Direct publishing
does not use a database outbox, so a process crash between the database commit
and Redis publish can leave a record that needs to be submitted again from the
app.

- `EXTRACTION_RUN_LEASE_SECONDS`: duration of a worker claim before recovery;
  defaults to 120 seconds.
- `EXTRACTION_RUN_HEARTBEAT_SECONDS`: interval for renewing an active claim;
  defaults to 30 seconds and is capped at half the lease duration.
- `REDIS_UNACKNOWLEDGED_IDLE_MS`: when Taskiq Redis may reclaim an unacknowledged
  message; defaults to 10 minutes.
- `REDIS_UNACKNOWLEDGED_LOCK_TIMEOUT_SECONDS`: expiry for Taskiq Redis's
  unacknowledged-message claim lock; defaults to 30 seconds.
