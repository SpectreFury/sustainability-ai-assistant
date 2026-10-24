## Sustainability AI Assistant

This is the KuKi sustainability AI assistant application. Had a lot of fun making this.

KuKi turns uploaded sustainability documents into source-linked facts, supports
evidence-backed questions, and builds Indian financial-year summaries from the
available records. It keeps document-reported values separate from calculations
made by the application.

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
sudo make dev
```

### What startup does

The launcher syncs backend dependencies, installs frontend dependencies when
needed, starts local Postgres and Redis with Docker Compose, applies database
migrations, then starts the API, extraction worker, and frontend together. Use
the root `.env` file for the credentials and service settings the launcher
requires; local Postgres and Redis are started with Compose.

This is just for the reviewer's ease of use and nothing more.

## Review the main workflows

After startup, open the frontend at [http://localhost:3000](http://localhost:3000)
and create an account. The dashboard includes:

- **Documents** at `/workspace/documents` to upload PDF or XLSX files, track
  processing, and review facts with their page or spreadsheet-cell evidence.
- **Ask AI** at `/workspace` to ask questions over selected documents and
  inspect citations, calculations, and gaps.
- **Financial-Year Summary** at `/workspace/financial-year` to select an Indian
  financial year, organization, and document scope and inspect coverage.
- **Evaluations** at `/workspace/evaluations` to run the source-backed case pack
  and inspect saved results.

The API's interactive examples are at [http://localhost:8000/docs](http://localhost:8000/docs).
The main API routes are `POST /documents/upload-signature` and
`POST /documents/{id}/complete` for uploads, `GET /documents` for processing
status, `POST /answers` for questions, `GET /financial-year/summary` for FY
totals, and `GET /evaluations/cases` plus `POST /evaluations/runs` for evaluation.
The browser handles the signed Cloudinary upload steps for documents.

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
  database, and the answer path does not use vector search. Server-side code
  performs and rechecks arithmetic and financial-year aggregation.
- **Observability:** Langfuse tracing is optional and can record extraction and
  answer calls when configured.

## Known limitations

I was severely hindered by the model quality, we constant hit rate limit with the gemini API and if given the choice, I would select a much powerful model for extraction.

However, even if we hit rate limiting, the system is build in a way that we retry and the processing mostly finishes.

## Images 

<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/e3b79162-297e-40ed-8ffd-76414f2a1315" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/a52c58a6-b94e-4690-adfd-d8e43b42e780" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/e8392b4c-2813-46af-a403-f97ab0ba96c0" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/f016345b-044c-41ad-b8c4-f998a4a4aba2" />
<img width="1920" height="961" alt="image" src="https://github.com/user-attachments/assets/8d1bb2f4-2d8e-4688-a671-03033a1eb1fa" />

## Evals Improvement

### V1
<img width="1906" height="959" alt="image" src="https://github.com/user-attachments/assets/9cd983f5-5762-4e7a-91f5-3b292950c776" />

### V4
<img width="1906" height="959" alt="image" src="https://github.com/user-attachments/assets/db013082-4891-4a77-a1a8-72dfc3e8edcf" />



