import { cpSync, existsSync } from "node:fs";

// O servidor standalone resolve assets relativamente ao próprio server.js.
for (const directory of [".next/static", "public"]) {
  if (existsSync(directory)) cpSync(directory, ".next/standalone/" + directory, { recursive: true });
}
