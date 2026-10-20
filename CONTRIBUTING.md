# Contributing

Keep the one-repository contract: the static web studio must work independently
from the optional API, and the CLI must work without a browser or web gateway.

Start with `npm ci`, `npm test`, `npm run build` and `npm run check:release`.
For native work, run `python3 -m unittest discover -s native -v`. For backend work,
install its development requirements and run `python3 -m pytest backend/tests -q`.
FFmpeg is required for real conversion tests. The full UNO test is opt-in; see
the native README. Do not substitute simulation for a real-camera/native claim.

Use `npm run format` for web JavaScript, HTML, CSS and documentation. UI colors
belong in `dist/tokens.css`; media/demo palette colors are content. Respect the
world switch, reduced motion, keyboard controls and sharp paper surfaces.
Keep `dist/ods.js` as the single ODS writer implementation.

Changes to frame limits, palette order or version semantics need compatibility
checks across `dist/core.js`, `native/cli.py`, `native/bridge.py`, and `backend/`.
Preserve bounded queues, file sizes, subprocess timeouts and controller cleanup.

Describe the trigger, expected behavior, actual behavior, OS/browser or
LibreOffice version, and a small reproducible sample in a bug report. Do not
attach private footage, pairing tokens, credentials or identifying camera data.
Explain actual checks in a pull request, including untested device behavior.

By contributing, you agree to license your contributions under the repository's
MIT license. Please be direct, kind and specific in reviews.
