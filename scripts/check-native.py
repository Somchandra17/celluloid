#!/usr/bin/env python3
"""Opt-in real Calc readbacks and CLI snapshot acceptance on a matched UNO runtime."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "native"))

from native import cli
from native.bridge import launch_renderer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Final static ODS snapshot (must not already exist)")
    parser.add_argument("--lo-binary", help="LibreOffice executable")
    parser.add_argument("--uno-port", type=int, default=2187)
    args = parser.parse_args()
    if not 1 <= args.uno_port <= 65535:
        parser.error("UNO port must be between 1 and 65535")
    output = args.output.resolve()
    if output.exists():
        parser.error("Choose a new output path; acceptance does not overwrite files")
    output.parent.mkdir(parents=True, exist_ok=True)
    url = f"uno:socket,host=127.0.0.1,port={args.uno_port};urp;StarOffice.ComponentContext"
    previous_url = os.environ.get("CELLULOID_TEST_UNO_URL")
    owned = None
    try:
        renderer, owned = launch_renderer(args.lo_binary, args.uno_port, headless=True)
        os.environ["CELLULOID_TEST_UNO_URL"] = url
        suite = unittest.defaultTestLoader.discover(str(ROOT / "native"), "test_native_integration.py")
        checks = unittest.TextTestRunner(verbosity=2).run(suite)
        if not checks.wasSuccessful() or checks.testsRun != 2 or checks.skipped:
            return 1

        with tempfile.TemporaryDirectory(prefix="celluloid-native-check-") as directory:
            clip = Path(directory) / "clip.json"
            clip.write_text(json.dumps({"version": 1, "width": 4, "height": 2, "fps": 8,
                                        "palette": ["#000000", "#ff0000", "#00ff00"],
                                        "frames": [[1, 1, 0, 0, 2, 2, 2, 0],
                                                   [1, 2, 0, 0, 2, 2, 2, 0]]}))
            result = cli.main(["play", str(clip), "--uno-url", url, "--save", str(output)])
            if result:
                return result
        with zipfile.ZipFile(output) as archive:
            assert archive.testzip() is None, "Snapshot ZIP CRC failed"
            assert archive.read("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet"
        document = renderer.desktop.loadComponentFromURL(output.as_uri(), "_blank", 0, ())
        if document is None:
            raise RuntimeError("Calc did not reopen its saved snapshot")
        try:
            sheet = document.Sheets.getByIndex(0)
            actual = [[sheet.getCellByPosition(x, y).CellBackColor for x in range(4)]
                      for y in range(2)]
            assert actual == [[0xff0000, 0x00ff00, 0, 0], [0x00ff00, 0x00ff00, 0x00ff00, 0]], actual
        finally:
            document.close(True)
        print(f"Real Calc frames, CLI playback and reopened static ODS readback passed: {output}")
        return 0
    finally:
        if previous_url is None:
            os.environ.pop("CELLULOID_TEST_UNO_URL", None)
        else:
            os.environ["CELLULOID_TEST_UNO_URL"] = previous_url
        if owned:
            owned.close()


if __name__ == "__main__":
    raise SystemExit(main())
