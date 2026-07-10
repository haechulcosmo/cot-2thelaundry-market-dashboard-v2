import { mkdir, cp, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const dist = path.join(root, "dist");
const publicDir = path.join(dist, "public");
const serverDir = path.join(dist, "server");
const hostingDir = path.join(dist, ".openai");

if (existsSync(dist)) {
  await rm(dist, { recursive: true, force: true });
}

await mkdir(publicDir, { recursive: true });
await mkdir(serverDir, { recursive: true });
await mkdir(hostingDir, { recursive: true });

await cp(path.join(root, "index.html"), path.join(publicDir, "index.html"));
await cp(path.join(root, "history.html"), path.join(publicDir, "history.html"));
await cp(path.join(root, "cloud.js"), path.join(publicDir, "cloud.js"));
await cp(path.join(root, ".openai", "hosting.json"), path.join(hostingDir, "hosting.json"));

const serverCode = `import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(__dirname, "../public");

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp"
};

function safePathname(url) {
  const pathname = new URL(url).pathname;
  if (pathname === "/" || pathname === "") return "/index.html";
  return pathname;
}

export default {
  async fetch(request) {
    const pathname = safePathname(request.url);
    const filePath = path.join(publicDir, pathname.replace(/^\\/+/, ""));
    try {
      const body = await readFile(filePath);
      const ext = path.extname(filePath).toLowerCase();
      return new Response(body, {
        headers: {
          "content-type": contentTypes[ext] || "application/octet-stream",
          "cache-control": "no-cache"
        }
      });
    } catch {
      const body = await readFile(path.join(publicDir, "index.html"));
      return new Response(body, {
        status: pathname.endsWith(".html") ? 200 : 404,
        headers: {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "no-cache"
        }
      });
    }
  }
};
`;

await writeFile(path.join(serverDir, "index.js"), serverCode, "utf-8");
