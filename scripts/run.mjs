#!/usr/bin/env node
/**
 * Dispatcher for: dev | start | seed | migrate | test | lint
 * Always runs inside the project's isolated backend/.venv (auto-bootstraps).
 */
import { runSync, startServer, py, ensureSetup } from "./lib.mjs";

const cmd = process.argv[2] || "dev";
const p = () => py();

switch (cmd) {
  case "dev":
    startServer({ reload: true });
    break;
  case "start":
    startServer({ reload: false });
    break;
  case "seed":
    ensureSetup({ quiet: true });
    runSync([...p(), "-m", "app.seed"]);
    break;
  case "migrate":
    ensureSetup({ quiet: true });
    runSync([...p(), "-m", "alembic", "upgrade", "head"]);
    break;
  case "test":
    ensureSetup({ quiet: true });
    runSync([...p(), "-m", "pytest", "tests", "-q"]);
    break;
  case "lint":
    ensureSetup({ quiet: true });
    runSync([...p(), "-m", "ruff", "check", "app", "tests", "--select", "E9,F"]);
    break;
  default:
    console.error(`[JEEVAN] Unknown script "${cmd}". Use: dev | start | seed | migrate | test | lint`);
    process.exit(1);
}
