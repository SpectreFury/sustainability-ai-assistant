## Sustainability AI Assistant

## Tech stack

- **Frontend:** Next.js, React, Chakra UI, Tailwind CSS, TanStack Query, Zod.
- **Backend:** Python, FastAPI, Pydantic, PostgreSQL, SQLAlchemy, Alembic.
- **Background jobs:** TaskIQ and Redis.
- **Document storage and parsing:** Cloudinary, PyMuPDF, OpenPyXL.
- **AI:** Gemini (`gemini-3.5-flash-lite`) through LangChain Google GenAI.
- **Observability:** Langfuse (optional).
- **Authentication:** JWT and bcrypt.

## Coding tools used

- Harness - Opencode (Go plan bought specifically for this task)
- Models: GPT 6 Luna, Big Pickles, Deepseek V4.1 flash

## Run locally

### Requirements

- Node.js
- Python (uv)
- Make (mostly there in linux and mac)

**PS**: I want to make your life easier so that you can run this locally and hence I am $\color{red}{\text{INTENTIONALLY}}$ committing my .env, I know this is stupid in all scenarios, I just want you to have no friction when you verify the project.

### Windows

```powershell
.\dev.ps1
```

If Windows blocks the script because of the PowerShell execution policy, run it
for this session with:

```powershell
powershell -ExecutionPolicy Bypass -File .\dev.ps1
```

### Mac/Linux

```sh
make dev
```

## Architecture

### Upload Flow
<img width="1670" height="987" alt="image" src="https://github.com/user-attachments/assets/20901716-217f-4b3a-8a68-c2e35c13f35a" />

### Process Flow
<img width="2050" height="1364" alt="image" src="https://github.com/user-attachments/assets/0369f267-0b21-478a-9a5f-18831fa5bc15" />

### Answer Flow
<img width="1840" height="1260" alt="image" src="https://github.com/user-attachments/assets/363e17cf-1fdf-4b51-b190-c185bf925b73" />




## Reviewer account

The latest evaluation result will be visible in the reviewer account. I’ll send
the account details by email.

## Approach and design choices

- **Frontend:** Next.js, React, and Tailwind CSS.
- **API and data:** FastAPI, SQLAlchemy, and Postgres store accounts, document
  metadata, extracted facts, evidence locations, and answers.
- **Files and background work:** documents are uploaded to Cloudinary; Redis
  with Taskiq queues longer-running jobs so the API can return promptly.
- **GenAI:** Gemini extracts structured facts from PDF and XLSX content and
  drafts evidence-grounded answers. The application retrieves relevant facts
  from Postgres and prepares the evidence context; the model does not query the
  database.
- **Observability:** Langfuse tracing is optional and can record extraction and
  answer calls when configured.

Additionally, I have added user authentication to this project even if it was not required. This is a full JWT based system with email and password login and all the document answers are user specific.

## Known limitations

I was severely hindered by the model quality, we constant hit rate limit with the gemini API and if given the choice, I would select a much powerful model for extraction. However, even if we hit rate limiting, the system is build in a way that we retry and the processing mostly finishes.

## What I would do to make this production-ready

- **Stream assistant responses:** Add Server-Sent Events (SSE) backed by Redis
  Streams, with interruption handling so users can stop an in-progress response.
- **Improve document extraction:** Use a much stronger extraction model or
  switch to vision-language-model-powered OCR for more reliable extraction.

## Images 

- [Figma](https://www.figma.com/design/IMcBx55NlhcK0LrtkusSGi/Untitled?node-id=0-1&t=eRt6XRTLh8DcC2VN-1)

<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/e3b79162-297e-40ed-8ffd-76414f2a1315" />
<img width="1906" height="959" alt="image" src="https://github.com/user-attachments/assets/e7ca37a4-8fb0-4927-a848-23d0d06e7be5" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/a52c58a6-b94e-4690-adfd-d8e43b42e780" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/e8392b4c-2813-46af-a403-f97ab0ba96c0" />
<img width="1919" height="957" alt="image" src="https://github.com/user-attachments/assets/f016345b-044c-41ad-b8c4-f998a4a4aba2" />
<img width="1920" height="961" alt="image" src="https://github.com/user-attachments/assets/8d1bb2f4-2d8e-4688-a671-03033a1eb1fa" />





