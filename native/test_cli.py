"""CLI checks: bounded decoding, latest-frame backpressure, scheduling and cleanup."""

import argparse
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from native import cli


def sample_clip(count=4):
    return {"version": 1, "width": 2, "height": 1, "fps": 10,
            "palette": ["#000000", "#ffffff"],
            "frames": [[i % 2, (i + 1) % 2] for i in range(count)]}


class ClipTests(unittest.TestCase):
    def test_quantization_matches_browser_boundaries(self):
        raw = bytes([0, 0, 0, 255, 255, 255, 25, 26, 77, 128, 128, 128])
        self.assertEqual(cli.quantize_rgb(raw, "color"), [0, 215, 8, 129])
        self.assertEqual(cli.quantize_rgb(raw, "mono"), [0, 1, 0, 1])
        self.assertEqual(cli.quantize_rgb(bytes([0, 0, 0, 255, 255, 255]), "grayscale"), [0, 15])
        self.assertEqual(len(cli.make_palette("color")), 216)
        self.assertEqual(cli.make_palette("mono"), ["#171c24", "#f8f4e9"])

    def test_clip_rejects_corrupt_and_out_of_bounds_frames(self):
        for key, value in (("width", True), ("height", 91), ("fps", float("nan")),
                           ("palette", ["red"]), ("frames", [[True, 0]]),
                           ("frames", [[2, 0]]), ("frames", []), ("frames", [[0]])):
            clip = {**sample_clip(), key: value}
            with self.subTest(key=key, value=value), self.assertRaises(cli.CLIError):
                cli.validate_clip(clip)

    def test_loader_accepts_browser_export_and_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.json"
            path.write_text(json.dumps(sample_clip()))
            self.assertEqual(cli.load_clip(path), sample_clip())
            path.write_text("not JSON")
            with self.assertRaisesRegex(cli.CLIError, "valid UTF-8 JSON"):
                cli.load_clip(path)

    def test_only_local_regular_files_are_accepted(self):
        with self.assertRaises(cli.CLIError), patch.object(cli, "run_command") as command:
            cli.convert_video("https://example.com/clip.mp4")
        command.assert_not_called()

    def test_portrait_dimensions_stay_bounded(self):
        self.assertEqual(cli.dimensions(160, 1080, 1920), (51, 90))
        self.assertEqual(cli.dimensions(48, 1920, 1080), (48, 27))

    def test_probe_honors_sample_aspect_and_rotation(self):
        metadata = {"streams": [{"width": 720, "height": 576, "sample_aspect_ratio": "16:15",
                                  "side_data_list": [{"rotation": -90}]}], "format": {"duration": "5.5"}}
        with patch.object(cli, "run_command", return_value=types.SimpleNamespace(stdout=json.dumps(metadata).encode())):
            self.assertEqual(cli.probe_video(Path("clip.mp4")), (576, 768, 5.5))

    def test_nonfinite_metadata_is_reported_as_a_validation_error(self):
        for rotation in ("inf", "-inf", "nan"):
            metadata = {"streams": [{"width": 64, "height": 36,
                                      "side_data_list": [{"rotation": rotation}]}]}
            with self.subTest(rotation=rotation), patch.object(
                    cli, "run_command", return_value=types.SimpleNamespace(stdout=json.dumps(metadata).encode())):
                with self.assertRaisesRegex(cli.CLIError, "metadata"):
                    cli.probe_video(Path("clip.mp4"))


class SchedulingTests(unittest.TestCase):
    def test_finite_playback_keeps_the_last_frame_for_its_full_interval(self):
        now = [0.]
        engine = cli.Engine(cli.SimulatedRenderer())
        cli.play_clip(engine, sample_clip(4), clock=lambda: now[0],
                      sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertAlmostEqual(now[0], .4)
        self.assertIsNone(engine.session)

    def test_slow_calc_drops_overdue_frames_and_reaches_final_frame(self):
        now = [0.]
        renderer = cli.SimulatedRenderer()
        original_render = renderer.render

        def slow_render(runs, palette):
            original_render(runs, palette)
            now[0] += .26

        renderer.render = slow_render
        engine = cli.Engine(renderer)
        stats = cli.play_clip(engine, sample_clip(6), loops=1, clock=lambda: now[0],
                              sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual((stats.rendered, stats.skipped), (3, 3))
        self.assertEqual(renderer.cells, [0xffffff, 0])
        self.assertIsNone(engine.session)

    def test_loops_use_increasing_sequences(self):
        now = [0.]
        engine = cli.Engine(cli.SimulatedRenderer())
        sequences = []
        original_frame = engine.frame

        def record_frame(data):
            sequences.append(data["sequence"])
            return original_frame(data)

        engine.frame = record_frame
        stats = cli.play_clip(engine, sample_clip(3), loops=2, clock=lambda: now[0],
                              sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual(sequences, list(range(6)))
        self.assertEqual((stats.rendered, stats.skipped), (6, 0))

    def test_interrupt_ends_session(self):
        engine = cli.Engine(cli.SimulatedRenderer())
        with self.assertRaises(KeyboardInterrupt):
            cli.play_clip(engine, sample_clip(), sleep=Mock(side_effect=KeyboardInterrupt))
        self.assertIsNone(engine.session)


class CameraTests(unittest.TestCase):
    def camera_args(self, **changes):
        values = dict(device="/dev/video0", input_format="v4l2", capture_size="640x480", capture_fps=30, fps=8,
                      width=2, palette="mono", mirror=False, ffmpeg="ffmpeg", duration=1)
        return argparse.Namespace(**{**values, **changes})

    def test_mailbox_replaces_backlog_with_latest_frame(self):
        mailbox = cli.LatestFrame()
        for sequence in range(1000):
            mailbox.put(sequence, b"frame")
        self.assertEqual(mailbox.get_after(-1), (999, b"frame"))
        self.assertIsNone(mailbox.get_after(999, timeout=0))
        mailbox.finish()
        self.assertIsNone(mailbox.get_after(999))

    def test_reader_preserves_partial_reads_and_rejects_partial_final_frame(self):
        stream = Mock()
        stream.read.side_effect = [b"ab", b"c", b"d", b""]
        mailbox = cli.LatestFrame()
        cli.read_camera_frames(stream, 3, mailbox)
        self.assertEqual(mailbox.latest, (0, b"abc"))
        self.assertIsInstance(mailbox.error, cli.CLIError)
        self.assertTrue(mailbox.done)

    def test_camera_commands_use_explicit_devices_and_platform_formats(self):
        self.assertEqual(cli.camera_format("auto", "darwin"), "avfoundation")
        self.assertEqual(cli.camera_format("auto", "win32"), "dshow")
        self.assertEqual(cli.camera_format("auto", "linux"), "v4l2")
        command = cli.camera_command(self.camera_args(input_format="dshow", device="Built-in Webcam", mirror=True), 48, 36)
        self.assertIn("video=Built-in Webcam", command)
        self.assertEqual(command[command.index("-framerate") + 1], "30")
        self.assertIn("fps=8,scale=48:36:flags=area,setsar=1,hflip", command)
        self.assertNotIn("shell", command)

    def test_camera_bounded_decode_uses_actual_engine(self):
        process = Mock()
        process.stdout = io.BytesIO(bytes([0, 0, 0, 255, 255, 255]) * 40)
        process.poll.return_value = 0
        process.returncode = 0
        engine = cli.Engine(cli.SimulatedRenderer())
        # A 2-column 4:3 grid is 2 rows, so each frame is twelve bytes.
        with patch.object(cli.subprocess, "Popen", return_value=process):
            stats = cli.stream_camera(engine, self.camera_args())
        self.assertGreaterEqual(stats.rendered, 1)
        self.assertEqual(stats.rendered + stats.skipped, 20)
        self.assertIsNone(engine.session)
        self.assertTrue(process.stdout.closed)

    def test_camera_interrupt_terminates_decoder_and_ends_engine(self):
        process = Mock()
        process.stdout = io.BytesIO(b"")
        process.poll.return_value = None
        engine = cli.Engine(cli.SimulatedRenderer())
        with patch.object(cli.subprocess, "Popen", return_value=process), \
                patch.object(cli.LatestFrame, "get_after", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                cli.stream_camera(engine, self.camera_args())
        process.terminate.assert_called()
        self.assertTrue(process.stdout.closed)
        self.assertIsNone(engine.session)

    def test_camera_failure_includes_actionable_device_error(self):
        process = Mock()
        process.stdout = io.BytesIO(b"")
        process.poll.return_value = 1
        process.returncode = 1
        with patch.object(cli.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(cli.CLIError, "Check --device"):
                cli.stream_camera(cli.Engine(cli.SimulatedRenderer()), self.camera_args())


class MainTests(unittest.TestCase):
    def test_script_and_module_entrypoints(self):
        root = Path(__file__).resolve().parents[1]
        for arguments in ([sys.executable, "-m", "native.cli", "--help"],
                          [sys.executable, "native/cli.py", "--help"]):
            result = subprocess.run(arguments, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("webcam", result.stdout)

    def test_play_json_simulation_needs_no_uno_or_web_server(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.json"
            path.write_text(json.dumps(sample_clip(1)))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                result = cli.main(["play", str(path), "--simulate"])
            self.assertEqual(result, 0, errors.getvalue())
            self.assertIn("1 frames rendered", errors.getvalue())

    def test_owned_libreoffice_is_cleaned_up_after_interrupt(self):
        owned = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.json"
            path.write_text(json.dumps(sample_clip(1)))
            with patch.object(cli, "launch_renderer", return_value=(cli.SimulatedRenderer(), owned)), \
                    patch.object(cli, "play_clip", side_effect=KeyboardInterrupt), \
                    contextlib.redirect_stderr(io.StringIO()):
                result = cli.main(["play", str(path)])
        self.assertEqual(result, 130)
        owned.close.assert_called_once()

    def test_save_uses_native_calc_ods_filter(self):
        fake_uno = types.SimpleNamespace(createUnoStruct=lambda name: types.SimpleNamespace())
        renderer = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"uno": fake_uno}):
            path = Path(directory) / "frame.ods"
            self.assertEqual(cli.save_snapshot(renderer, path), path)
            url, properties = renderer.document.storeAsURL.call_args.args
            self.assertEqual(url, path.as_uri())
            self.assertEqual([(item.Name, item.Value) for item in properties], [("FilterName", "calc8"), ("Overwrite", True)])

    def test_rejects_nonfinite_parameters_before_launching_calc(self):
        with patch.object(cli, "launch_renderer") as launch, contextlib.redirect_stderr(io.StringIO()):
            result = cli.main(["webcam", "--device", "/dev/video0", "--fps", "nan"])
        self.assertEqual(result, 1)
        launch.assert_not_called()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires FFmpeg and ffprobe")
class FFmpegIntegrationTests(unittest.TestCase):
    def test_real_video_to_json_to_simulated_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                     "-i", "testsrc2=size=64x36:rate=8", "-t", "0.5", "-threads", "1",
                                     "-c:v", "mpeg4", str(source)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            clip = cli.convert_video(source, width=16, fps=8, duration=.5, palette="color")
            cli.validate_clip(clip)
            self.assertEqual((clip["width"], clip["height"], len(clip["frames"])), (16, 9, 4))
            self.assertEqual(len(clip["palette"]), 216)
            output = Path(directory) / "clip.celluloid.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["convert", str(source), "-o", str(output), "--width", "16",
                                           "--fps", "8", "--duration", ".5", "--palette", "color"]), 0)
            self.assertEqual(cli.load_clip(output), clip)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["play", str(output), "--simulate", "--fps", "30"]), 0)


if __name__ == "__main__":
    unittest.main()
