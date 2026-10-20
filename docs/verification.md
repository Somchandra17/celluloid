# Verification record

19 October 2026, release 1.2.2. This distinguishes completed checks from
device-dependent work. Local checks ran under Node 24 and Python 3.12.

Automated totals: 28 JavaScript checks, 51 native/CLI/process checks, 29 installer
checks and 29 API checks pass (137 total); two real-UNO checks are skipped by default. The ODS
structural validation command also passes. The model-only real-UNO check was
run separately and passed as described below.

## Completed

- JavaScript core tests: palette mapping, spreadsheet coordinates, changing sample
  frames, JSON validation/round trip, recorded-clip transformation, and ODS bytes.
- DOM integration tests with mocked media: upload conversion/seek lifecycle,
  camera permission denial, camera recording and track cleanup, source switching,
  repeat cancellation, export actions, and authenticated native frame delivery
  with latest-frame backpressure. These are not real-camera/browser codec tests.
- FFmpeg API integration: generated actual video files, color/grayscale/mono,
  portrait aspect ratio, malformed inputs, frame truncation, upload bounds,
  concurrency, chunked uploads, and companion-origin CORS.
- Native companion: HTTP session/frame/stop, bearer auth, origin/Host validation,
  palette/frame validation, changed-range rendering, error recovery and isolated
  process launch/cleanup. Optional full UNO integration test is included but is
  not enabled by the default test command.
- ODS: ZIP CRC, XML namespaces, actual cell fill styles, hidden RGB storage,
  embedded Basic/library metadata, grid/frame bounds and chunk boundaries.
- A generated ODS was opened and rendered to PDF using LibreOffice 26.8.
- Actual direct UNO check: created a Calc document, locked controller updates,
  painted two real cells red, unlocked controllers and read back RGB 16711680.
- Actual multi-frame Calc model check: 4 × 2 cells, first frame 8 changed cells
  in 4 ranges, second frame 1 changed cell in 1 range, unchanged frame 0 writes.
  Exact RGB readbacks and controller unlocking passed. Reported render times
  were approximately 5.2, 1.9 and 1.0 ms for this tiny grid; these are not a
  throughput claim for larger footage. The remote model was initialized directly,
  bypassing desktop factory/view loading. The isolated test peaked near 111 MiB.
- Standalone CLI tests include real FFmpeg conversion into shared indexed JSON,
  simulated Calc playback, elapsed-time scheduling, skipped frames, bounded live
  camera buffering, platform device arguments, interruption/cleanup, and snapshot
  save arguments. The CLI imports no web framework or NumPy.
- The local Node server serves HTML/JS/CSS, handles HEAD, rejects write methods
  and preserves missing-asset 404 status.
- Visual world switching preserves media/export data. Interface colors are
  tokenized, reduced-motion rules exist, and bundled font binaries are real
  variable WOFF2 with their licenses included.
- The Vercel static configuration is checked locally against the deployment
  contract. The Node-only build validates assets, generates a reproducible source
  archive, and reads it back to verify checksums and exact source contents.
- Regression checks cover repeated conversion cancellation, bounded subprocess
  output and cleanup, invalid rotation metadata, matching monochrome mapping,
  first-frame decode readiness, final-frame duration, failed Calc session
  replacement, malformed HTTP targets and case-colliding/archive alias paths.
- Setup tests cover apt/dnf/pacman, Homebrew and WinGet plans; matching app/Python
  selection; repeat setup without reinstallation; dry-run/check/no-install and
  browser-only modes; failed imports/installs; explicit paths with spaces;
  occupied ports; own-child readiness; and shutdown. A real POSIX smoke test
  serves HTML/JavaScript through the browser-only launcher and stops on Ctrl+C.
  Package managers and native office launch are mocked: no package installation
  on a physical Mac/Windows machine is claimed. Separate CI jobs now cover
  installer tests on Linux/macOS/Windows and PowerShell syntax; their first run
  in the maintainer's account is pending.
- Launcher readiness is now exercised against the actual bridge main/banner and
  HTTP server in a child process, with only native office construction stubbed.
  It serves the app after readiness and performs normal shutdown. This caught
  the 1.2.0 mismatch between the real `libreoffice` mode and the launcher's
  invented `native` label. A user-provided Mac log showed successful UNO/bridge
  startup and studio asset delivery before that false timeout; it does not
  establish sustained Calc playback or camera capture.
- Camera tests verify the request happens directly on Enable camera, persistent
  feedback while a request is pending, late-grant track cleanup after source
  changes, blocked policy/insecure context detection, saved-denial guidance and
  busy-device errors. Physical Arc/macOS permission dialogs remain unverified.
- Closed-socket reproduction: the old port probe rejected a released port with
  no listening process; a reusable bind accepted that same port. Both setup and
  native startup now use that reusable POSIX probe while still rejecting live
  listeners. This matches the user's empty Mac `lsof ... -sTCP:LISTEN` report.
- A real POSIX launcher/bridge/process test starts both listeners, sends Ctrl+C
  twice, waits for a deliberately stubborn synthetic office process to stop,
  verifies removal of its temporary profile and restarts immediately on the same
  ports. Both runs pass. A separate test checks an office child whose original
  launcher already exited. These are real process/socket lifecycle checks with
  synthetic office software; they do not establish full Mac Calc rendering.

## Not established in this environment

- Real-device webcam permission/capture and browser codec compatibility. The
  session exposed no supported browser-control tool, so no visual browser QA or
  physical camera test is claimed.
- Desktop factory startup, sustained native Calc playback speed, full CLI
  native acceptance and embedded Basic macro execution. A bounded retry on the
  supplied LibreOfficeDev 26.8 alpha was stopped near 822 MiB during
  `loadComponentFromURL("private:factory/scalc", ...)`, before grid setup; hidden
  loading did not resolve it. A separately extracted 26.8.1 runtime failed
  `initNew` with an application error. The working model-only test used a
  distribution pyuno client with matching client registries over UNO to the
  bundled server. These results identify a runtime-specific blocker and do not
  validate the normal desktop startup path. No hidden-model workaround is
  shipped in the application.
- Windows/macOS Python UNO setup. The README gives the requirement and a verified
  protocol, not a claim that an installer has been validated on every platform.
- A deployment on the maintainer's own Vercel account. That plan was dropped:
  the project is not to be hosted there. The first GitHub Actions run is still
  a separate account-side check.

The opt-in `scripts/check-native.py` and manual GitHub Actions workflow now
reproduce full document-start, CLI playback, saved ODS reopening and final-color
readbacks on a distribution-matched installation. The command's help/imports and
syntax were checked here; a successful complete run on that target is pending.

The application labels simulation, browser preview and native rendering
separately. Requested FPS is a setting; native render time is measured by the
companion. A matched stable LibreOffice/Python UNO installation and local camera
are the appropriate next acceptance-test environment.
