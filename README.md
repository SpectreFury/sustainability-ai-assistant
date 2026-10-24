## Sustainability AI Assistant

This is the KuKi sustainability AI assistant application.

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

Sets up docker and redis locally, does migration and start the frontend, backend, and the worker in a single terminal.

This is just for the reviewer's ease of use and nothing more.

