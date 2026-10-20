import test from "node:test";
import assert from "node:assert/strict";
import {
  mkdtemp,
  mkdir,
  writeFile,
  rm,
  readFile,
  symlink,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  collectSourceFiles,
  createSourceZip,
  assertPortableFiles,
  isPortablePath,
  crc32,
  ROOT,
  validateStaticFiles,
} from "../scripts/build.mjs";
import {
  readSourceZip,
  validateDeployment,
} from "../scripts/check-release.mjs";

test("toolkit contains portable source and excludes local recordings, secrets, caches and deployment state", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "celluloid-release-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const names = [
    "README.md",
    "dist/index.html",
    "native/bridge.py",
    "setup_celluloid.py",
    "setup.sh",
    "setup.cmd",
    "scripts/bootstrap-windows.ps1",
    ".github/workflows/ci.yml",
    "dist/downloads/toolkit.zip",
    ".git/config",
    ".openai/site.json",
    ".vercel/project.json",
    "node_modules/example/index.js",
    "native/__pycache__/bridge.pyc",
    "backend/.env",
    "native/credentials.json",
    "dist/uploads/private.json",
    "dist/private.mp4",
    "exports/session.json",
    "personal.txt",
  ];
  for (const name of names) {
    await mkdir(path.dirname(path.join(root, name)), { recursive: true });
    await writeFile(path.join(root, name), name);
  }
  const files = await collectSourceFiles(root);
  assert.deepEqual(
    files.map((file) => file.path),
    [
      ".github/workflows/ci.yml",
      "README.md",
      "dist/index.html",
      "native/bridge.py",
      "scripts/bootstrap-windows.ps1",
      "setup.cmd",
      "setup.sh",
      "setup_celluloid.py",
    ],
  );
  assertPortableFiles(files);
  const archive = createSourceZip(files),
    decoded = readSourceZip(archive);
  assert.deepEqual(decoded, files);
  assert.ok(
    archive.equals(createSourceZip([...files].reverse())),
    "archive must not depend on traversal order",
  );
});

test("source packaging rejects symlinks instead of reading outside the repository", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "celluloid-symlink-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, "dist"));
  await writeFile(path.join(root, "README.md"), "source");
  await symlink("../README.md", path.join(root, "dist", "linked.txt"));
  await assert.rejects(collectSourceFiles(root), /symlinks/);
});

test("release inspection detects stale host identity and corrupted archive bytes", () => {
  const hosted = ["https://previous", ".chatgpt", ".site"].join("");
  assert.throws(
    () =>
      assertPortableFiles([{ path: "README.md", data: Buffer.from(hosted) }]),
    /hosted-site identity/,
  );
  assert.equal(isPortablePath("dist/uploads/clip.json"), false);
  assert.equal(isPortablePath("backend/.env.production"), false);
  assert.equal(crc32(Buffer.from("123456789")), 0xcbf43926);
  const archive = createSourceZip([
    { path: "README.md", data: Buffer.from("portable source") },
  ]);
  archive[30 + Buffer.byteLength("celluloid/README.md")] ^= 1;
  assert.throws(() => readSourceZip(archive), /checksum mismatch/);
});

test("Vercel config serves only the static app, permits its camera and preserves missing-asset 404s", async () => {
  const config = JSON.parse(
    await readFile(path.join(ROOT, "vercel.json"), "utf8"),
  );
  const packageJson = { scripts: { build: "node scripts/build.mjs" } };
  validateDeployment(config, packageJson);
  assert.throws(
    () =>
      validateDeployment(
        {
          ...config,
          rewrites: [{ source: "/(.*)", destination: "/index.html" }],
        },
        packageJson,
      ),
    /missing assets/,
  );
  assert.throws(
    () => validateDeployment({ ...config, outputDirectory: "." }, packageJson),
    /serve dist/,
  );
});

test("static validation understands data URLs containing SVG fragment references", async () => {
  await validateStaticFiles(ROOT);
});

test("portable ZIP rejects aliases and case-insensitive filename collisions", () => {
  const file = (name) => ({ path: name, data: Buffer.from("source") });
  assert.throws(
    () => createSourceZip([file("dist/A.js"), file("dist/a.js")]),
    /collision/,
  );
  for (const name of [
    "dist/./app.js",
    "dist//index.html",
    "dist/CON.txt",
    "dist/name.",
    "dist/name:stream",
  ])
    assert.throws(() => createSourceZip([file(name)]), /Noncanonical/);
  // Modify both ZIP name records without changing data checksums, independently
  // exercising the reader rather than relying on the builder's preflight.
  function renamedZip(from, to) {
    const zip = createSourceZip([file("dist/A.js"), file(from)]);
    const before = Buffer.from("celluloid/" + from),
      after = Buffer.from("celluloid/" + to);
    assert.equal(before.length, after.length);
    for (
      let at = zip.indexOf(before);
      at !== -1;
      at = zip.indexOf(before, at + after.length)
    )
      after.copy(zip, at);
    return zip;
  }
  assert.throws(
    () => readSourceZip(renamedZip("dist/B.js", "dist/a.js")),
    /Unsafe ZIP entry/,
  );
  assert.throws(
    () => readSourceZip(renamedZip("dist/x/a.js", "dist/./a.js")),
    /Noncanonical/,
  );
});
