import { mkdir, cp, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const dist = path.join(root, "dist");

if (existsSync(dist)) {
  await rm(dist, { recursive: true, force: true });
}

await mkdir(dist, { recursive: true });
await cp(path.join(root, "index.html"), path.join(dist, "index.html"));
await cp(path.join(root, "history.html"), path.join(dist, "history.html"));
await cp(path.join(root, "cloud.js"), path.join(dist, "cloud.js"));
