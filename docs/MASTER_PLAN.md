# Celluloid — master plan and execution log

Owner: Som Chandra. Started 19 October 2026.

## Outcome

Deliver one GitHub-ready repository that can be imported into Vercel for the
browser studio and used locally from a terminal to render video or live camera
frames through real LibreOffice Calc cells. Keep Som's terminal/darkroom design
and the existing upload, webcam, recording and ODS workflows intact.

The initial pipeline and portable 1.1.0 release are already built. This pass
closes verification gaps and fixes concrete defects found during acceptance
testing. It does not restart the project or add unrelated features.

## Phase 1 — establish the baseline

- [x] Review the current implementation, clean release and known limitations.
- [x] Write this plan before starting further implementation.
- [x] Assign bounded native and release reviews.

Baseline evidence before this pass: 22 JavaScript checks, 35 native/CLI checks and 20 FFmpeg API
checks pass. Source packaging is reproducible and a fresh portable checkout
builds independently from the original preview host. ODS structure/opening and
individual real Calc cell updates were checked. Sustained native playback and
embedded Basic macro execution are not yet established.

## Phase 2 — prove the real spreadsheet path

1. Reproduce the native integration failure using a dedicated temporary profile
   and matching LibreOffice/UNO runtime. Put explicit time and memory bounds
   around experiments; stop a failing process before it threatens the workspace.
2. Inspect document creation, grid sizing and controller updates individually.
   Fix an application defect if one is identified rather than attributing every
   failure to the environment.
3. Run two distinct frames through the actual renderer and read cell backgrounds
   back through UNO. Verify unchanged-cell skipping and controller unlocking.
4. If the runtime is reliable, exercise CLI playback, static snapshot saving,
   and an exported document's embedded macro. Record exact results and limits.
5. Verify live-stream transport using a generated source where possible. Keep
   synthetic-source evidence separate from physical webcam/OS permission tests.

Acceptance: actual changed Calc cells are read back correctly for more than one
frame, or a specific reproducible environment blocker is documented. Do not call
simulation an end-to-end native success. No real camera access is needed while
Som is away.

## Phase 3 — release and lifecycle hardening

- [x] Review the CLI, companion, backend and source packaging for concrete
      correctness, cleanup, resource-bound and cross-platform defects.
- [x] Fix substantiated issues and add focused regression tests.
- [x] Ensure error paths release camera/decoder/owned office processes, restore
      controller notifications and preserve user-owned office sessions.
- [x] Keep browser and CLI frame contracts compatible and live queues bounded.
- [x] Check that portable artifacts exclude credentials, account IDs, caches,
      private footage and the original host's Git history.

Acceptance: the relevant tests pass after each fix; no unrelated rewrites or
additional account integrations are introduced.

## Phase 4 — final release gates

The delivery handoff records completion of these final gates: affected checks,
web build/release inspection, regenerated source archive, synchronized clean
GitHub repository, no hosting identity or preconfigured remote, and the existing
private preview refreshed with the exact committed source. Verification notes,
the changelog and this execution log are included in that source archive.

Acceptance: a downloadable source artifact matches the tested source and has a
clear Vercel import path and terminal setup instructions.

## Work requiring Som's account or hardware

These are recorded handoff items, not silent assumptions of success:

- Publish the repository under Som's chosen GitHub account/name and visibility.
- Import it into Som's Vercel account and configure the chosen domain's DNS.
- Check a physical camera and its OS permissions on the target computer.
- Validate Windows/macOS UNO setup on matching installed releases.
- Perform visual browser QA when a supported browser-control surface is
  available; none is currently exposed in this session.

## Execution log

- Plan written before further changes. Native integration and focused release
  review are the next actions. Routine reversible work is authorized; no
  account credentials or approvals are requested while Som rests.
- Two bounded reviews completed. Fixed decoder cancellation ownership, bounded
  subprocess output, nonfinite rotation metadata, API monochrome consistency,
  first decoded upload readiness, the CLI's final-frame interval, failed Calc
  replacement cleanup, native port conflicts and malformed HTTP targets.
- Portable ZIP construction and inspection now reject aliases, reserved desktop
  filenames and case-insensitive collisions.
- Actual multi-frame Calc model readbacks passed: 8 cells/4 ranges, then 1 cell/1
  range, then 0 unchanged writes. Controller unlocking and RGB values passed.
  Desktop factory/view startup remains blocked by the supplied runtime before
  grid setup. No model-only workaround was added to production.
- Prepared `scripts/check-native.py` and a manual GitHub Actions workflow for a
  matched Calc/UNO installation. It checks full document creation, actual CLI
  playback, snapshot saving/reopening and final colors. Its complete target-side
  run is pending; physical camera and Basic macro acceptance remain separate.
- Release 1.1.1 validation: 24 JavaScript, 48 native/CLI/process and 29 API checks
  pass (101 total), plus ODS structural validation. Two full/native opt-in tests
  are skipped by default; the model-only one passed separately. Detailed scope
  and runtime limits are recorded in [verification](verification.md).
- Release 1.2.0 adds the shared cross-platform setup engine and OS entrypoints:
  native installation/discovery, browser/bridge startup, repeat runs, read-only
  checks, custom paths/ports, optional FFmpeg and browser-only mode. The setup
  guide and web pairing instructions use these entrypoints. Installer regression
  tests and three-OS CI coverage are included; target-machine installations are
  not substituted with mock-test claims.
