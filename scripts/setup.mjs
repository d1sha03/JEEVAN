#!/usr/bin/env node
/** npm run setup — one-time (idempotent) bootstrap: venv + deps + migrate + seed. */
import { ensureSetup } from "./lib.mjs";

console.log("[JEEVAN] Setting up the platform ...");
ensureSetup();
console.log("\n[JEEVAN] Setup complete. Start it with:  npm run dev");
console.log("[JEEVAN] Then open http://localhost:8000");
console.log("[JEEVAN] Sign in: admin@jeevan.app / Jeevan@123 (all roles share this password)\n");
