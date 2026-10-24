import { createHash } from "node:crypto"
import { createInterface } from "node:readline"
import { spawn, spawnSync } from "node:child_process"
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const backend = join(root, "backend")
const app = join(root, "app")
const envFile = join(root, ".env")
const isWindows = process.platform === "win32"
const children = new Map()
let infrastructureStarted = false
let stopping = false
let resolveFinished
const finished = new Promise((resolvePromise) => {
  resolveFinished = resolvePromise
})

function parseEnv(contents) {
  const values = {}
  for (const sourceLine of contents.split(/\r?\n/)) {
    const line = sourceLine.trim()
    if (!line || line.startsWith("#")) continue
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/)
    if (!match) continue

    let value = match[2].trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      const quote = value[0]
      value = value.slice(1, -1)
      if (quote === '"') {
        value = value.replace(/\\n/g, "\n").replace(/\\r/g, "\r").replace(/\\t/g, "\t")
      }
    } else {
      value = value.replace(/\s+#.*$/, "").trim()
    }
    values[match[1]] = value
  }
  return values
}

function loadRootEnv() {
  if (!existsSync(envFile)) {
    throw new Error(
      `Missing ${envFile}. Copy .env.example to .env, fill in the required credentials, and run this command again.`,
    )
  }

  const values = parseEnv(readFileSync(envFile, "utf8"))
  for (const [key, value] of Object.entries(values)) {
    if (process.env[key] === undefined) process.env[key] = value
  }
  process.env.NEXT_PUBLIC_BACKEND_URL ||= "http://localhost:8000"

  const missing = [
    "DATABASE_URL",
    "REDIS_URL",
    "JWT_SECRET_KEY",
    "CLOUDINARY_CLOUD_NAME",
    "CLOUDINARY_API_KEY",
    "CLOUDINARY_API_SECRET",
  ].filter((key) => !process.env[key]?.trim())
  if (!process.env.GEMINI_API_KEY?.trim() && !process.env.GOOGLE_API_KEY?.trim()) {
    missing.push("GEMINI_API_KEY")
  }
  if (missing.length) {
    throw new Error(`Set these values in .env before starting: ${missing.join(", ")}`)
  }
}

function runSetup(label, command, args, cwd = root) {
  console.log(`\n==> ${label}`)
  const result = spawnSync(command, args, {
    cwd,
    env: process.env,
    stdio: "inherit",
    shell: isWindows,
    windowsHide: true,
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`${label} failed with exit code ${result.status ?? 1}.`)
  }
}

function requireCommand(command, args, label) {
  const result = spawnSync(command, args, {
    cwd: root,
    env: process.env,
    stdio: "ignore",
    shell: isWindows,
    windowsHide: true,
  })
  if (result.error || result.status !== 0) {
    throw new Error(`${label} is required. Install it and run this command again.`)
  }
}

function ensureFrontendDependencies() {
  const lockPath = join(app, "package-lock.json")
  const modulesPath = join(app, "node_modules")
  const markerPath = join(modulesPath, ".kuki-package-lock-hash")
  const lockHash = createHash("sha256").update(readFileSync(lockPath)).digest("hex")
  let installedHash = ""
  if (existsSync(markerPath)) installedHash = readFileSync(markerPath, "utf8").trim()

  if (!existsSync(join(modulesPath, ".bin", isWindows ? "next.cmd" : "next")) || installedHash !== lockHash) {
    runSetup("Installing frontend dependencies from package-lock.json", "npm", ["ci"], app)
    mkdirSync(modulesPath, { recursive: true })
    writeFileSync(markerPath, `${lockHash}\n`)
  }
}

function prefixOutput(name, stream) {
  const lines = createInterface({ input: stream })
  lines.on("line", (line) => console.log(`[${name}] ${line}`))
}

function startService(name, command, args, cwd) {
  const child = spawn(command, args, {
    cwd,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
    shell: isWindows,
    detached: !isWindows,
    windowsHide: true,
  })
  children.set(name, child)
  prefixOutput(name, child.stdout)
  prefixOutput(name, child.stderr)
  child.once("error", (error) => {
    console.error(`[${name}] Could not start: ${error.message}`)
    void shutdown(1)
  })
  child.once("exit", (code, signal) => {
    children.delete(name)
    if (!stopping) {
      console.error(`[${name}] exited (${signal ?? code ?? "unknown status"}); stopping the other services.`)
      void shutdown(code && code !== 0 ? code : 1)
    }
  })
  return child
}

function terminate(child) {
  if (!child.pid || child.killed) return
  if (isWindows) {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    })
    return
  }
  try {
    process.kill(-child.pid, "SIGTERM")
  } catch {
    child.kill("SIGTERM")
  }
}

async function shutdown(exitCode = 0) {
  if (stopping) return
  stopping = true
  console.log("\nStopping API, worker, frontend, Postgres, and Redis...")

  const activeChildren = [...children.values()]
  activeChildren.forEach(terminate)
  let stopTimeout
  const stoppedGracefully = await Promise.race([
    Promise.all(activeChildren.map((child) => new Promise((resolvePromise) => {
      if (child.exitCode !== null || child.signalCode !== null) return resolvePromise()
      child.once("exit", resolvePromise)
    }))).then(() => true),
    new Promise((resolvePromise) => {
      stopTimeout = setTimeout(() => resolvePromise(false), 5000)
    }),
  ])
  clearTimeout(stopTimeout)

  if (!stoppedGracefully && !isWindows) {
    for (const child of activeChildren) {
      if (child.exitCode !== null || child.signalCode !== null || !child.pid) continue
      try {
        process.kill(-child.pid, "SIGKILL")
      } catch {
        child.kill("SIGKILL")
      }
    }
  }

  if (infrastructureStarted) {
    try {
      runSetup(
        "Stopping local Postgres and Redis (their data volumes are kept)",
        "docker",
        ["compose", "--env-file", ".env", "-f", "backend/docker-compose.yml", "down"],
      )
    } catch (error) {
      console.error(`Could not stop local infrastructure cleanly: ${error.message}`)
      exitCode ||= 1
    }
  }
  process.exitCode = exitCode
  resolveFinished()
}

async function main() {
  loadRootEnv()
  requireCommand("uv", ["--version"], "uv")
  requireCommand("npm", ["--version"], "Node.js and npm")
  requireCommand("docker", ["compose", "version"], "Docker Compose v2")

  runSetup("Syncing backend dependencies", "uv", ["sync", "--locked"], backend)
  ensureFrontendDependencies()
  runSetup(
    "Starting local Postgres and Redis",
    "docker",
    ["compose", "--env-file", ".env", "-f", "backend/docker-compose.yml", "up", "-d", "--wait", "postgres", "redis"],
  )
  infrastructureStarted = true
  runSetup("Applying database migrations", "uv", ["run", "alembic", "upgrade", "head"], backend)

  console.log("\nKuKi is starting:")
  console.log("  Frontend: http://localhost:3000")
  console.log("  API:      http://localhost:8000")
  console.log("  Stop all services with Ctrl+C. Database volumes are preserved.\n")

  startService(
    "api",
    "uv",
    ["run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"],
    backend,
  )
  startService(
    "worker",
    "uv",
    [
      "run",
      "taskiq",
      "worker",
      "--log-level",
      "INFO",
      "--workers",
      "1",
      "--max-async-tasks",
      "4",
      "--ack-type",
      "when_executed",
      "broker:broker",
      "workers.extraction",
    ],
    backend,
  )
  startService("frontend", "npm", ["run", "dev"], app)

  process.once("SIGINT", () => void shutdown(130))
  process.once("SIGTERM", () => void shutdown(143))
  await finished
}

main().catch((error) => {
  console.error(`\nLocal startup failed: ${error.message}`)
  if (children.size > 0 || infrastructureStarted) void shutdown(1)
  else process.exitCode = 1
})
