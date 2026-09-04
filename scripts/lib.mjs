#!/usr/bin/env node
/**
 * JEEVAN shared bootstrap (cross-platform: Windows / macOS / Linux).
 *
 * Guarantees an isolated interpreter for the project:
 *   1. uses backend/.venv if present
 *   2. otherwise locates a system Python (python / python3 / py -3)
 *   3. `ensureSetup()` creates the venv + installs deps + migrates + seeds
 *
 * This avoids the classic Windows problem where `python` resolves to one
 * interpreter while `uvicorn` comes from an unrelated venv on PATH.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const BACKEND = path.join(ROOT, "backend");
export const VENV = path.join(BACKEND, ".venv");
export const VENV_PY = process.platform === "win32"
  ? path.join(VENV, "Scripts", "python.exe")
  : path.join(VENV, "bin", "python");

export function findSystemPython() {
  const candidates = process.platform === "win32"
    ? [["python"], ["py", "-3"], ["python3"]]
    : [["python3"], ["python"]];
  for (const cmd of candidates) {
    const r = spawnSync(cmd[0], [...cmd.slice(1), "--version"], { stdio: "ignore" });
    if (r.status === 0) return cmd;
  }
  return null;
}

export function venvReady() {
  return existsSync(VENV_PY);
}

/** Returns the interpreter argv-prefix: [".venv/python"] or a system python. */
export function py() {
  if (venvReady()) return [VENV_PY];
  const sys = findSystemPython();
  if (!sys) {
    console.error("\n[JEEVAN] Python 3.11+ was not found on this machine.");
    console.error("[JEEVAN] Install it from https://www.python.org/downloads/");
    console.error("[JEEVAN] On Windows, tick 'Add python.exe to PATH' during setup,");
    console.error("[JEEVAN] then open a NEW terminal and run:  npm run setup\n");
    process.exit(1);
  }
  return sys;
}

export function runSync(args, opts = {}) {
  const argv = Array.isArray(args) ? args : [args];
  const r = spawnSync(argv[0], argv.slice(1), {
    cwd: BACKEND, stdio: "inherit", shell: false, ...opts,
  });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

/** Full first-run bootstrap: venv -> deps -> migrations -> seed. Idempotent. */
export function ensureSetup({ quiet = false } = {}) {
  if (!venvReady()) {
    const sys = py();
    if (!quiet) console.log(`[JEEVAN] Creating isolated environment at backend${path.sep}.venv ...`);
    runSync([...sys, "-m", "venv", VENV], { cwd: ROOT });
    if (!venvReady()) {
      console.error("[JEEVAN] Could not create the virtual environment.");
      console.error("[JEEVAN] On Debian/Ubuntu: sudo apt install python3-venv, then retry.");
      process.exit(1);
    }
  }
  const pyx = [VENV_PY];
  if (!quiet) console.log("[JEEVAN] Installing Python dependencies (fast if already present) ...");
  runSync([...pyx, "-m", "pip", "install", "--disable-pip-version-check",
           "-q", "-r", "requirements.txt"]);
  if (!quiet) console.log("[JEEVAN] Applying database migrations ...");
  runSync([...pyx, "-m", "alembic", "upgrade", "head"]);
  if (!quiet) console.log("[JEEVAN] Seeding demo data ...");
  runSync([...pyx, "-m", "app.seed"]);
  return pyx;
}

/** Start the API server (async — streams logs, respects Ctrl+C). */
export function startServer({ reload = false } = {}) {
  ensureSetup({ quiet: !process.env.JEEVAN_VERBOSE });
  const port = process.env.PORT || "8000";
  const args = [VENV_PY, "-m", "uvicorn", "app.main:app",
    "--host", "0.0.0.0", "--port", port];
  if (reload) args.push("--reload");
  console.log(`\n[JEEVAN] Starting on http://localhost:${port}  (Ctrl+C to stop)\n`);
  const child = spawn(args[0], args.slice(1), {
    cwd: BACKEND, stdio: "inherit", shell: false,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  const stop = () => { try { child.kill("SIGINT"); } catch { /* noop */ } };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  child.on("exit", (code) => process.exit(code ?? 0));
}
