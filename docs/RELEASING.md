# Preparing a GitHub release

From a fresh clone with Node 22+ and Python 3.10+:

```sh
npm ci
npm test
npm run build
npm run check:release
python3 -m unittest discover -s native -v
python3 -m unittest discover -s tests -p test_setup.py -v
python3 tests/test_ods.py
```

Install the backend dev requirements and FFmpeg to run its integration suite.
Record any skipped device/UNO checks honestly. Check the repository contains
the license, Vercel configuration, docs, CI and CLI before pushing.

On a matched LibreOffice/Python UNO installation, also run
`/usr/bin/python3 scripts/check-native.py --output /tmp/celluloid-final.ods`
with a new output path, or trigger **Real LibreOffice acceptance (manual)** in
GitHub Actions. It checks actual cell readbacks, CLI playback and saved ODS
reopening. Physical camera capture, graphical playback speed and embedded Basic
execution still need separate acceptance checks. See [verification](verification.md).

## Publish your repository

For GitHub's browser upload, follow [UPLOAD_TO_GITHUB.md](../UPLOAD_TO_GITHUB.md).
Extract the ZIP and upload its contents at the repository root. Dragging the
ZIP itself stores an archive rather than usable source.
The commands below are the alternative Git route.

The portable toolkit/release directory deliberately has no hosting account
metadata or preconfigured Git remote. If it is not already a Git checkout:

```sh
git init -b main
git add .
git commit -m "Initial open-source release"
```

Create an empty repository in your own GitHub account, then add its actual URL:

```sh
git remote add origin https://github.com/YOUR_ACCOUNT/celluloid.git
git push -u origin main
```

Replace `YOUR_ACCOUNT` with your account. No account handle is guessed in this
source. Check GitHub Actions. Repository visibility remains a choice in your own
account. This preparation does not create a public repository or change your
portfolio's domain.

`npm run build` generates the source toolkit using a strict allowlist and fixed
ZIP metadata. `npm run check:release` reads the archive back, checks checksums,
verifies exact source contents and validates deployment configuration. Generated
downloads are ignored by Git and rebuilt on Vercel/CI. They are available in the
release source archive as a build product when explicitly packaged for delivery.

Do not commit `.openai/`, `.vercel/`, `.env` files, tokens, local media, decoder
outputs, node_modules or caches. The ignore rules and source allowlist are both
intentional; neither should be bypassed when preparing a release.
