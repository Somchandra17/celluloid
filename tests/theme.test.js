import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("interface colors use tokens while media palettes stay independent", async () => {
  const [styles, app, html, tokens] = await Promise.all(
    ["styles.css", "app.js", "index.html", "tokens.css"].map((name) =>
      readFile(new URL("../dist/" + name, import.meta.url), "utf8"),
    ),
  );
  assert.doesNotMatch(styles, /#[0-9a-f]{3,8}\b/i);
  assert.doesNotMatch(app, /#[0-9a-f]{3,8}\b/i);
  assert.doesNotMatch(html.split("<body>")[1], /#[0-9a-f]{3,8}\b/i);
  for (const token of [
    "--accent-nerdy",
    "--accent-creative",
    "--grain-opacity",
    "--canvas-chrome",
    "--radius",
  ])
    assert.ok(tokens.includes(token));
  assert.match(styles, /prefers-reduced-motion/);
  assert.match(html, /data-world-button="creative"/);
});

test("self-hosted font files are real WOFF2 and ship their licenses", async () => {
  for (const name of ["space-grotesk", "geist-mono"]) {
    const bytes = await readFile(
      new URL("../dist/assets/fonts/" + name + ".woff2", import.meta.url),
    );
    assert.equal(bytes.subarray(0, 4).toString(), "wOF2");
    const license = await readFile(
      new URL("../dist/assets/fonts/" + name + "-OFL.txt", import.meta.url),
      "utf8",
    );
    assert.match(license, /SIL OPEN FONT LICENSE/i);
  }
});
