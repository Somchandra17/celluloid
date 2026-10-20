import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";

test("local Node server serves the studio and preserves asset 404s", async (t) => {
  const process = spawn(globalThis.process.execPath, ["scripts/serve.mjs"], {
    cwd: new URL("../", import.meta.url),
    env: { ...globalThis.process.env, PORT: "0" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  t.after(() => process.kill());
  const address = await new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(Error("Local server did not start")),
      5000,
    );
    process.stdout.on("data", (chunk) => {
      const found = chunk.toString().match(/http:\/\/127\.0\.0\.1:\d+/);
      if (found) {
        clearTimeout(timeout);
        resolve(found[0]);
      }
    });
    process.on("error", reject);
    process.on("exit", (code) => {
      if (code) reject(Error("Server exited: " + code));
    });
  });
  const index = await fetch(address + "/");
  assert.equal(index.status, 200);
  assert.match(await index.text(), /motion,/);
  const script = await fetch(address + "/app.js");
  assert.equal(script.status, 200);
  assert.match(script.headers.get("content-type"), /javascript/);
  const missing = await fetch(address + "/missing.js");
  assert.equal(missing.status, 404);
  assert.match(await missing.text(), /wrong cell/);
  const head = await fetch(address + "/styles.css", { method: "HEAD" });
  assert.equal(head.status, 200);
  assert.equal(await head.text(), "");
  const post = await fetch(address + "/", { method: "POST" });
  assert.equal(post.status, 405);
  process.kill();
  await once(process, "exit");
});
