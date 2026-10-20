/** Static site validation and reproducible source packaging. Node only: no Python or FFmpeg. */
import { readFile, readdir, lstat, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = fileURLToPath(new URL("../", import.meta.url));
export const ARCHIVE_PATH = "dist/downloads/toolkit.zip";
const sourceDirectories = new Set([
  "dist",
  "backend",
  "native",
  "docs",
  "tests",
  "scripts",
  ".github",
]);
const sourceRootFiles = new Set([
  "README.md",
  "UPLOAD_TO_GITHUB.md",
  "LICENSE",
  "CHANGELOG.md",
  "CONTRIBUTING.md",
  "SECURITY.md",
  "CODE_OF_CONDUCT.md",
  "DESIGN.md",
  "package.json",
  "package-lock.json",
  "pyproject.toml",
  "requirements.txt",
  "package_toolkit.py",
  "setup_celluloid.py",
  "setup.sh",
  "setup.cmd",
  "vercel.json",
  ".gitignore",
  ".env.example",
]);
const excludedDirectories = new Set([
  ".git",
  ".openai",
  ".vercel",
  "node_modules",
  ".venv",
  "venv",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  ".cache",
  ".coverage",
  "coverage",
  "htmlcov",
  "downloads",
  "uploads",
  "uploaded",
  "media",
  "recordings",
  "exports",
  "artifacts",
  "test-results",
  "playwright-report",
]);
const excludedExtensions =
  /\.(?:py[co]|log|zip|tar|gz|ods|xlsx?|celluloid\.json|mp4|webm|mov|mkv|avi|wav|mp3|pem|key|p12|pfx)$/i;
const textExtensions =
  /\.(?:html|css|[cm]?js|json|py|md|txt|ya?ml|toml|svg|sh|cmd|ps1)$/i;

/** File names must survive extraction on case-insensitive desktop filesystems. */
export function portablePathKey(relativePath) {
  if (
    typeof relativePath !== "string" ||
    relativePath !== relativePath.normalize("NFC")
  )
    throw new Error(`Noncanonical source path: ${relativePath}`);
  const segments = relativePath.split("/");
  if (
    segments.some(
      (segment) =>
        !segment ||
        segment === "." ||
        segment === ".." ||
        /[\u0000-\u001f<>:"|?*\\]/.test(segment) ||
        /[. ]$/.test(segment) ||
        /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(segment),
    )
  )
    throw new Error(`Noncanonical source path: ${relativePath}`);
  return relativePath.toLowerCase();
}

export function isPortablePath(relativePath) {
  const parts = relativePath.split("/");
  if (parts.some((part) => excludedDirectories.has(part))) return false;
  if (parts.some((part) => part.startsWith(".env") && part !== ".env.example"))
    return false;
  if (parts.some((part) => /^(?:credentials|secrets?)(?:\.|$)/i.test(part)))
    return false;
  if (excludedExtensions.test(relativePath) || parts.at(-1) === ".DS_Store")
    return false;
  return parts.length === 1
    ? sourceRootFiles.has(parts[0])
    : sourceDirectories.has(parts[0]);
}

/** An explicit source allowlist prevents personal uploads and hosting state entering downloads. */
export async function collectSourceFiles(root = ROOT) {
  const files = [];
  async function visit(directory, prefix = "") {
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    for (const entry of entries) {
      const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (excludedDirectories.has(entry.name)) continue;
      if (
        !prefix &&
        !sourceRootFiles.has(entry.name) &&
        !sourceDirectories.has(entry.name)
      )
        continue;
      const absolutePath = path.join(directory, entry.name);
      if (entry.isSymbolicLink())
        throw new Error(`Source symlinks are not packaged: ${relativePath}`);
      if (entry.isDirectory()) {
        if (isPortablePath(`${relativePath}/placeholder`))
          await visit(absolutePath, relativePath);
      } else if (entry.isFile() && isPortablePath(relativePath)) {
        files.push({ path: relativePath, data: await readFile(absolutePath) });
      }
    }
  }
  await visit(root);
  return files;
}

export function assertPortableFiles(files) {
  const names = new Set();
  for (const file of files) {
    const key = portablePathKey(file.path);
    if (names.has(key))
      throw new Error(`Portable source path collision: ${file.path}`);
    names.add(key);
    if (!isPortablePath(file.path))
      throw new Error(`Private or generated file in release: ${file.path}`);
    if (
      !textExtensions.test(file.path) &&
      !["LICENSE", ".gitignore"].includes(
        file.path,
      )
    )
      continue;
    const source = file.data.toString("utf8");
    if (/https?:\/\/[^\s/"'<>]+\.chatgpt\.site\b/i.test(source)) {
      throw new Error(`Previous hosted-site identity in ${file.path}`);
    }
    if (
      /["'](?:site_id|siteId|orgId|projectId)["']\s*:\s*["'][^"']+["']/.test(
        source,
      )
    ) {
      throw new Error(`Hosting account identity in ${file.path}`);
    }
    if (/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(source)) {
      throw new Error(`Private key in ${file.path}`);
    }
  }
}

export function crc32(data) {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++)
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** Stored ZIP entries have fixed metadata, so identical source produces identical bytes everywhere. */
export function createSourceZip(files) {
  const localParts = [],
    directoryParts = [];
  let offset = 0;
  const sorted = [...files].sort((a, b) =>
    a.path < b.path ? -1 : a.path > b.path ? 1 : 0,
  );
  if (sorted.length > 65535)
    throw new Error("Too many source files for a portable ZIP");
  const names = new Set();
  for (const file of sorted) {
    const key = portablePathKey(file.path);
    if (names.has(key))
      throw new Error(`Portable archive path collision: ${file.path}`);
    names.add(key);
    if (
      !isPortablePath(file.path) ||
      file.path.includes("\\") ||
      file.path.split("/").includes("..")
    )
      throw new Error(`Unsafe archive path: ${file.path}`);
    const name = Buffer.from(`celluloid/${file.path}`),
      data = Buffer.from(file.data);
    if (data.length > 50 * 1024 * 1024)
      throw new Error(`Unexpectedly large source file: ${file.path}`);
    const checksum = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(33, 12); // 1980-01-01, 00:00
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    localParts.push(local, name, data);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(0x0314, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(33, 14);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE((0o100644 << 16) >>> 0, 38);
    central.writeUInt32LE(offset, 42);
    directoryParts.push(central, name);
    offset += local.length + name.length + data.length;
  }
  const directory = Buffer.concat(directoryParts),
    end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(sorted.length, 8);
  end.writeUInt16LE(sorted.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...localParts, directory, end]);
}

export async function validateStaticFiles(root = ROOT) {
  const output = path.join(root, "dist");
  for (const file of [
    "index.html",
    "404.html",
    "research.html",
    "app.js",
    "core.js",
    "ods.js",
    "styles.css",
  ]) {
    if (!(await lstat(path.join(output, file))).isFile())
      throw new Error(`Missing static entry: ${file}`);
  }
  const files = await collectSourceFiles(root);
  const knownPaths = new Set(files.map((file) => file.path));
  knownPaths.add(ARCHIVE_PATH);
  for (const file of files.filter((file) => file.path.startsWith("dist/"))) {
    let references = [];
    const source = file.data.toString("utf8");
    if (file.path.endsWith(".html"))
      references = [
        ...source.matchAll(/\b(?:src|href)\s*=\s*["']([^"']+)["']/g),
      ].map((match) => match[1]);
    if (file.path.endsWith(".js"))
      references = [
        ...source.matchAll(/(?:\bfrom\s*|\bimport\s*)["'](\.[^"']+)["']/g),
      ].map((match) => match[1]);
    if (file.path.endsWith(".css"))
      references = [
        ...source.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]+))\s*\)/g),
      ].map((match) => match[1] ?? match[2] ?? match[3]);
    for (const reference of references) {
      if (
        !reference ||
        reference.startsWith("#") ||
        /^(?:[a-z]+:|\/\/)/i.test(reference)
      )
        continue;
      const target = new URL(
        reference,
        `https://static.invalid/${file.path.slice(5)}`,
      );
      let relative = decodeURIComponent(target.pathname).replace(/^\//, "");
      if (!relative || relative.endsWith("/")) relative += "index.html";
      if (!knownPaths.has(`dist/${relative}`))
        throw new Error(
          `Broken static reference in ${file.path}: ${reference}`,
        );
    }
  }
  return files;
}

export async function build(root = ROOT) {
  const files = await validateStaticFiles(root);
  assertPortableFiles(files);
  const archive = createSourceZip(files),
    destination = path.join(root, ARCHIVE_PATH);
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, archive);
  return { files: files.length, bytes: archive.length, archive: destination };
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    const result = await build();
    console.log(
      `Static site validated. Packaged ${result.files} source files (${result.bytes.toLocaleString()} bytes) → ${ARCHIVE_PATH}`,
    );
  } catch (error) {
    console.error(`Build failed: ${error.message}`);
    process.exitCode = 1;
  }
}
