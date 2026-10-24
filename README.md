## Sustainability AI Assistant

## Tech stack

- Frontend - Next.js, Tailwind, Tanstack Query.
- Backend - FastAPI, PostgreSQL, SQLAlchemy, Alembic
- Workers - TaskIQ (Queue), Redis(Broker)
- Tools - Langfuse
- LLM APIS - gemini-3.5-flash-lite

## Coding tools used

- Harness - Opencode
- Models: GPT 6 Luna, Big Pickles, Deepseek V4.1 flash

## Run locally

**PS**: I want to make your life easier so that you can run this locally and hence I am **INTENTIONALLY** committing my .env, I know this is stupid in all scenarios, I just want you to have no friction when you verify the project.

### Windows

Install Docker Desktop with Compose v2, Node.js 20.9 or later (which includes
`npm`), and `uv`. Open PowerShell in the repository folder and run:

```powershell
.\dev.ps1
```

If Windows blocks the script because of the PowerShell execution policy, run it
for this session with:

```powershell
powershell -ExecutionPolicy Bypass -File .\dev.ps1
```

### Mac/Linux

Install Docker with Compose v2, Node.js 20.9 or later (which includes `npm`),
`uv`, and GNU Make. From the repository folder, run:

```sh
make dev
```

Run this as your normal repository user, without `sudo`.

## Architecture

### Upload Flow
<img width="1670" height="987" alt="image" src="https://github.com/user-attachments/assets/20901716-217f-4b3a-8a68-c2e35c13f35a" />

### Process Flow
<img width="2050" height="1364" alt="image" src="https://github.com/user-attachments/assets/0369f267-0b21-478a-9a5f-18831fa5bc15" />

### Answer Flow
<img width="1840" height="1260" alt="image" src="https://github.com/user-attachments/assets/363e17cf-1fdf-4b51-b190-c185bf925b73" />




## Evaluation cases and saved results

The current case pack is `kuki-dataset-v4` and contains 14 source-grounded cases
across the six files below. The cases check reported values, exact source
locations, uncertainty and missing-value behavior, and selected calculations.

- `Annual Electricity Consumption.xlsx`
- `Adani commercial electricity bill.pdf`
- `BESCOM Commercial Electricity Bill.pdf`
- `form 3 filled.docx.pdf`
- `quality_policy_nestle.pdf`
- `water_bill_invoice.pdf`

Completed evaluation results are persisted in Postgres and the repository
includes a portable SQL snapshot at
[`backend/evaluations/seeds/evaluation_runs.sql`](backend/evaluations/seeds/evaluation_runs.sql).
The snapshot contains these historical runs:

| Case-set version | Cases passing | Pass rate |
| --- | ---: | ---: |
| `kuki-dataset-v1` (initial run) | 2 / 11 | 18.2% |
| `kuki-dataset-v4` (current case pack) | 10 / 14 | 71.4% |

## Evals Improvement

### V1
<img width="1906" height="959" alt="image" src="https://github.com/user-attachments/assets/9cd983f5-5762-4e7a-91f5-3b292950c776" />

### V4
<img width="1906" height="959" alt="image" src="https://github.com/user-attachments/assets/db013082-4891-4a77-a1a8-72dfc3e8edcf" />

## Approach and design choices

- **Frontend:** Next.js, React, and Tailwind CSS.
- **API and data:** FastAPI, SQLAlchemy, and Postgres store accounts, document
  metadata, extracted facts, evidence locations, answers, and evaluation runs.
- **Files and background work:** documents are uploaded to Cloudinary; Redis
  with Taskiq queues extraction and evaluation work so the API can return while
  longer jobs run.
- **GenAI:** Gemini extracts structured facts from PDF and XLSX content and
  drafts evidence-grounded answers. The application retrieves relevant facts
  from Postgres and prepares the evidence context; the model does not query the
  database.
- **Observability:** Langfuse tracing is optional and can record extraction and
  answer calls when configured.

This Mermaid diagram uses features the terminal renderer doesn't support.
flowchart LR
    User[Reviewer] --> Web[Next.js dashboard]
    Web -->|API calls + auth cookies| API[FastAPI]

    Web -->|Upload using signed request| Cloudinary[(Cloudinary<br/>original files)]
    API -->|Sign upload / record completion| DB[(Postgres)]
    API -->|Read/write scoped records| DB
    API -->|Queue extraction or evaluation task| Redis[(Redis Streams)]
    Redis --> Worker[Taskiq worker]

    Worker -->|Download and verify source| Cloudinary
    Worker -->|Extract facts / evaluate answers| Gemini[Gemini API]
    Worker -->|Save facts, status, evaluation results| DB

    API -->|Load selected facts and source context| DB
    API -->|Send prepared context and question| Gemini
    Gemini -->|Draft structured answer| API
    API -->|Validate, save, return answer| DB
    API --> Web

    API -. optional traces .-> Langfuse[Langfuse]
    Worker -. optional traces .-> Langfuse

## Known limitations

I was severely hindered by the model quality, we constant hit rate limit with the gemini API and if given the choice, I would select a much powerful model for extraction.

However, even if we hit rate limiting, the system is build in a way that we retry and the processing mostly finishes.

## Images 

<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/e3b79162-297e-40ed-8ffd-76414f2a1315" />
<img width="1906" height="959" alt="image" src="https://github.com/user-attachments/assets/e7ca37a4-8fb0-4927-a848-23d0d06e7be5" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/a52c58a6-b94e-4690-adfd-d8e43b42e780" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/e8392b4c-2813-46af-a403-f97ab0ba96c0" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/f016345b-044c-41ad-b8c4-f998a4a4aba2" />
<img width="1920" height="961" alt="image" src="https://github.com/user-attachments/assets/8d1bb2f4-2d8e-4688-a671-03033a1eb1fa" />





