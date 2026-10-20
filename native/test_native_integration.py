"""Opt-in real Calc test; set CELLULOID_TEST_UNO_URL for an isolated LO process."""

import os
import unittest

from bridge import CalcRenderer, Engine, parse_session


@unittest.skipUnless(os.environ.get("CELLULOID_TEST_UNO_URL"), "Requires an isolated LibreOffice UNO process")
class NativeCalcTests(unittest.TestCase):
    def test_two_frames_in_direct_model_read_back_actual_colors(self):
        """Exercise real painting separately from desktop document/view creation.

        This test intentionally does not establish CalcRenderer.start or CLI
        acceptance: factory/view loading can fail independently in a headless
        runtime. No simulated renderer or replacement desktop is involved.
        """
        renderer = CalcRenderer(os.environ["CELLULOID_TEST_UNO_URL"])
        document = renderer.remote.ServiceManager.createInstanceWithContext(
            "com.sun.star.sheet.SpreadsheetDocument", renderer.remote)
        try:
            document.initNew()
            renderer.document = document
            renderer.sheet = document.Sheets.getByIndex(0)
            area = renderer.sheet.getCellRangeByPosition(0, 0, 3, 1)
            self.assertEqual((area.Columns.Count, area.Rows.Count), (4, 2))
            area.Columns.Width = 350
            area.Rows.Height = 350
            engine = Engine(renderer)
            engine.session = parse_session({"width": 4, "height": 2,
                                            "palette": ["#000000", "#ff0000", "#00ff00"]})
            session_id = engine.session.id

            def actual_colors():
                return [[renderer.sheet.getCellByPosition(x, y).CellBackColor
                         for x in range(4)] for y in range(2)]

            first = engine.frame({"sessionId": session_id, "sequence": 0,
                                  "pixels": [1, 1, 0, 0, 2, 2, 2, 0]})
            self.assertEqual(actual_colors(), [[0xff0000, 0xff0000, 0, 0],
                                               [0x00ff00, 0x00ff00, 0x00ff00, 0]])
            self.assertEqual((first["changedCells"], first["rangeWrites"]), (8, 4))
            second_pixels = [1, 2, 0, 0, 2, 2, 2, 0]
            second = engine.frame({"sessionId": session_id, "sequence": 1,
                                   "pixels": second_pixels})
            self.assertEqual(actual_colors(), [[0xff0000, 0x00ff00, 0, 0],
                                               [0x00ff00, 0x00ff00, 0x00ff00, 0]])
            self.assertEqual((second["changedCells"], second["rangeWrites"]), (1, 1))
            unchanged = engine.frame({"sessionId": session_id, "sequence": 2,
                                      "pixels": second_pixels})
            self.assertEqual((unchanged["changedCells"], unchanged["rangeWrites"]), (0, 0))
            self.assertFalse(document.hasControllersLocked())
        finally:
            document.close(True)

    def test_two_frames_read_back_actual_cell_colors(self):
        renderer = CalcRenderer(os.environ["CELLULOID_TEST_UNO_URL"])
        engine = Engine(renderer)
        try:
            session = engine.start({"width": 4, "height": 2,
                                    "palette": ["#000000", "#ff0000", "#00ff00"]})
            engine.frame({"sessionId": session["sessionId"], "sequence": 0,
                          "pixels": [1, 1, 0, 0, 2, 2, 2, 0]})
            result = engine.frame({"sessionId": session["sessionId"], "sequence": 1,
                                   "pixels": [1, 2, 0, 0, 2, 2, 2, 0]})
            actual = [[renderer.sheet.getCellByPosition(x, y).CellBackColor
                       for x in range(4)] for y in range(2)]
            self.assertEqual(actual, [[0xff0000, 0x00ff00, 0, 0],
                                      [0x00ff00, 0x00ff00, 0x00ff00, 0]])
            self.assertEqual(result["changedCells"], 1)
            self.assertEqual(result["rangeWrites"], 1)
            self.assertFalse(renderer.document.hasControllersLocked())
        finally:
            if renderer.document is not None:
                renderer.document.close(True)


if __name__ == "__main__":
    unittest.main()
