/** Check the exact downloadable artifact, not only the files in the checkout. */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { inflateRawSync } from "node:zlib";
import {
  ROOT,
  ARCHIVE_PATH,
  assertPortableFiles,
  collectSourceFiles,
  crc32,
  validateStaticFiles,
  portablePathKey,
} from "./build.mjs";

export function readSourceZip(archive) {
  if (
    archive.length < 22 ||
    archive.readUInt32LE(archive.length - 22) !== 0x06054b50
  )
    throw new Error("ZIP end record missing");
  const end = archive.length - 22;
  const count = archive.readUInt16LE(end + 10),
    start = archive.readUInt32LE(end + 16);
  let offset = start;
  const files = [],
    seen = new Set();
  for (let index = 0; index < count; index++) {
    if (offset + 46 > end || archive.readUInt32LE(offset) !== 0x02014b50)
      throw new Error("Invalid ZIP directory");
    const flags = archive.readUInt16LE(offset + 8),
      method = archive.readUInt16LE(offset + 10);
    const checksum = archive.readUInt32LE(offset + 16),
      compressedSize = archive.readUInt32LE(offset + 20),
      size = archive.readUInt32LE(offset + 24);
    const nameLength = archive.readUInt16LE(offset + 28),
      extraLength = archive.readUInt16LE(offset + 30),
      commentLength = archive.readUInt16LE(offset + 32);
    const localOffset = archive.readUInt32LE(offset + 42);
    const name = archive
      .subarray(offset + 46, offset + 46 + nameLength)
      .toString("utf8");
    const key = portablePathKey(name);
    if (
      !name.startsWith("celluloid/") ||
      name.includes("\\") ||
      name.split("/").includes("..") ||
      seen.has(key)
    )
      throw new Error(`Unsafe ZIP entry: ${name}`);
    if (flags & 1 || ![0, 8].includes(method))
      throw new Error(`Unsupported ZIP entry: ${name}`);
    seen.add(key);
    if (
      localOffset + 30 > start ||
      archive.readUInt32LE(localOffset) !== 0x04034b50
    )
      throw new Error(`Missing ZIP entry: ${name}`);
    const localNameLength = archive.readUInt16LE(localOffset + 26),
      localExtraLength = archive.readUInt16LE(localOffset + 28);
    const localName = archive
      .subarray(localOffset + 30, localOffset + 30 + localNameLength)
      .toString("utf8");
    if (localName !== name) throw new Error(`ZIP filename mismatch: ${name}`);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    if (size > 50 * 1024 * 1024 || dataOffset + compressedSize > start)
      throw new Error(`Invalid ZIP size: ${name}`);
    const packed = archive.subarray(dataOffset, dataOffset + compressedSize);
    const data =
      method === 0
        ? packed
        : inflateRawSync(packed, { maxOutputLength: 50 * 1024 * 1024 });
    if (data.length !== size || crc32(data) !== checksum)
      throw new Error(`ZIP checksum mismatch: ${name}`);
    files.push({ path: name.slice("celluloid/".length), data });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  if (offset !== end || offset - start !== archive.readUInt32LE(end + 12))
    throw new Error("ZIP directory size mismatch");
  return files;
}

export function validateDeployment(config, packageJson) {
  if (
    config.version !== 2 ||
    config.framework !== null ||
    config.outputDirectory !== "dist"
  )
    throw new Error("Vercel must serve dist as an Other/static project");
  if (
    config.buildCommand !== "npm run build" ||
    config.installCommand !== "npm ci"
  )
    throw new Error("Vercel must use the reproducible npm build");
  if (
    config.functions ||
    config.builds ||
    config.rewrites ||
    config.routes ||
    config.crons
  )
    throw new Error(
      "Static deployment must not route to a hosted backend or rewrite missing assets",
    );
  if (packageJson.scripts?.build !== "node scripts/build.mjs")
    throw new Error("package.json must expose the Node-only static build");
  const headers =
    config.headers?.find((rule) => rule.source === "/(.*)")?.headers ?? [];
  const byName = new Map(
    headers.map((header) => [header.key.toLowerCase(), header.value]),
  );
  if (
    byName.get("permissions-policy") !==
    "camera=(self), microphone=(), geolocation=()"
  )
    throw new Error(
      "Camera permissions must be local to this site; microphone and geolocation stay disabled",
    );
  if (
    byName.get("x-content-type-options") !== "nosniff" ||
    byName.get("referrer-policy") !== "strict-origin-when-cross-origin"
  )
    throw new Error("Static security headers are missing");
}

export async function checkRelease(root = ROOT) {
  const [config, packageJson, archive] = await Promise.all([
    readFile(path.join(root, "vercel.json"), "utf8").then(JSON.parse),
    readFile(path.join(root, "package.json"), "utf8").then(JSON.parse),
    readFile(path.join(root, ARCHIVE_PATH)),
  ]);
  validateDeployment(config, packageJson);
  await validateStaticFiles(root);
  const archived = readSourceZip(archive);
  assertPortableFiles(archived);
  const source = await collectSourceFiles(root);
  if (source.length !== archived.length)
    throw new Error("Download does not match source; run npm run build");
  const current = new Map(source.map((file) => [file.path, file.data]));
  for (const file of archived) {
    if (!current.get(file.path)?.equals(file.data))
      throw new Error(
        `Stale source in download: ${file.path}; run npm run build`,
      );
  }
  for (const required of [
    "README.md",
    "LICENSE",
    "package.json",
    "vercel.json",
    "dist/index.html",
    "native/bridge.py",
    "native/cli.py",
    "docs/CLI.md",
    "docs/VERCEL.md",
    "scripts/build.mjs",
  ]) {
    if (!current.has(required))
      throw new Error(`Release is missing ${required}`);
  }
  return { files: archived.length, bytes: archive.length };
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    const result = await checkRelease();
    console.log(
      `Release checked: ${result.files} portable source files; valid static Vercel config; toolkit matches current source.`,
    );
  } catch (error) {
    console.error(`Release check failed: ${error.message}`);
    process.exitCode = 1;
  }
}
