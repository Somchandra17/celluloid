/** Tiny loopback-only static development server; no Python runtime required. */
import http from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.resolve(fileURLToPath(new URL("../dist/", import.meta.url)));
const port = Number(process.env.PORT || 5173);
if (!Number.isInteger(port) || port < 0 || port > 65535)
  throw Error("PORT must be between 0 and 65535");
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".zip": "application/zip",
  ".txt": "text/plain; charset=utf-8",
};
const server = http.createServer(async (req, res) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader(
    "Permissions-Policy",
    "camera=(self), microphone=(), geolocation=()",
  );
  if (!["GET", "HEAD"].includes(req.method)) {
    res.writeHead(405, { Allow: "GET, HEAD" });
    res.end();
    return;
  }
  try {
    let requested = decodeURIComponent(
      new URL(req.url, "http://localhost").pathname,
    );
    if (requested.endsWith("/")) requested += "index.html";
    const file = path.resolve(root, "." + requested);
    if (!file.startsWith(root + path.sep) && file !== root)
      throw Error("Invalid path");
    if (!(await stat(file)).isFile()) throw Error("File not found");
    const data = await readFile(file);
    res.writeHead(200, {
      "Content-Type": types[path.extname(file)] || "application/octet-stream",
      "Content-Length": data.length,
    });
    res.end(req.method === "HEAD" ? undefined : data);
  } catch {
    const page = await readFile(path.join(root, "404.html")).catch(() =>
      Buffer.from("Not found"),
    );
    res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
    res.end(req.method === "HEAD" ? undefined : page);
  }
});
server.on("error", (e) => {
  console.error(`Cannot start studio: ${e.message}`);
  process.exitCode = 1;
});
server.listen(port, "127.0.0.1", () =>
  console.log(`Celluloid studio: http://127.0.0.1:${server.address().port}`),
);
