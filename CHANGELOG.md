# Changelog

## 1.2.2

- Fix false busy-port failures after shutdown on macOS/Linux: both setup and
  native startup probes now allow closed TCP connections in TIME_WAIT.
- Identify web and UNO ports separately in errors; `--port` changes the web
  address and `--uno-port` changes the LibreOffice listener.
- Restore Ctrl+C handlers when an interpreter inherits ignored SIGINT, protect
  cleanup from repeated interrupts, and stop owned office descendants even if
  their launcher has already exited.
- Real process/socket regression checks cover repeated Ctrl+C and immediate
  restarts on the same two ports, without requiring LibreOffice in the test.

## 1.2.1

- Fix a false setup timeout after a successful LibreOffice bridge launch: the
  readiness check now uses the bridge's actual `libreoffice` mode identifier.
- Reproduce the producer/launcher handshake with a real bridge server and a
  stubbed renderer so readiness tests cannot substitute an invented mode name.
- Persistent webcam request/error status and Arc/macOS permission guidance;
  distinguish blocked permissions, insecure contexts and busy cameras.
- Explicit local camera permissions policy and no-cache responses so a refreshed
  local studio loads updated camera controls.

## 1.2.0

- Shared cross-platform setup engine with Linux/macOS and Windows launchers.
- Package-manager installation, matching UNO runtime discovery, readiness checks
  and browser startup; no Node dependency for local studio/bridge use.
- Dry-run, check, install-only, existing-runtime and browser-only modes; optional
  FFmpeg installation and custom native executable/port options.
- Windows owned-office process-tree cleanup and graceful bridge shutdown signals.
- Installer regression suite, three-OS CI coverage and setup documentation.

## 1.1.1

- Keep conversion slots and temporary files owned until canceled decoder work finishes.
- Bound decoder diagnostics and metadata output, and reject nonfinite rotation metadata.
- Match API monochrome colors and threshold to the browser and CLI.
- Wait for the first decoded upload frame and show the final CLI frame for its full interval.
- Preserve the active Calc session when replacement setup fails; reject occupied native launch ports.
- Reject ambiguous or case-colliding source archive paths on desktop filesystems.
- Real multi-frame Calc model readbacks, a master plan, and opt-in native acceptance command/workflow.

## 1.1.0

- Standalone terminal conversion, playback and direct camera-to-Calc streaming.
- Static Vercel configuration and a Node-only reproducible build.
- Portable source packaging with hosting-state/media/credential exclusion checks.
- GitHub Actions for the web, release, ODS, companion, CLI and FFmpeg API.
- Som's tokenized terminal/darkroom visual worlds and self-hosted variable fonts.
- Single ODS writer, deployment/native/architecture guides and release checklist.

## 1.0.0

- Browser video conversion, webcam preview/recording and frame-data import/export.
- Animated ODS generation and optional token-protected native Calc companion.
- Optional bounded FFmpeg conversion API.
