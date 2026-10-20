"""Integration tests use real FFmpeg videos and the complete HTTP upload route."""
import asyncio
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading

from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
import pytest

from backend.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required for conversion integration tests")
    target = tmp_path_factory.mktemp("video") / "fixture.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=size=80x48:rate=10:duration=1", "-c:v", "mpeg4", str(target)
    ], check=True, timeout=20)
    return target


def upload(client, video: Path, **options):
    with video.open("rb") as source:
        return client.post("/api/convert", data=options,
                           files={"file": (video.name, source, "video/mp4")})


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["maxFrames"] == 240


@pytest.mark.parametrize("origin", ["http://localhost:8765", "http://127.0.0.1:8765"])
def test_native_companion_cors(client, origin):
    response = client.options("/api/convert", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("palette,colors", [("color", 216), ("grayscale", 16), ("mono", 2)])
def test_real_video_conversion(client, video, palette, colors):
    response = upload(client, video, width=32, fps=4, duration=0.75, palette=palette)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["version"] == 1
    assert result["width"] == 32
    assert result["height"] == 19
    assert result["fps"] == 4
    assert len(result["palette"]) == colors
    assert len(result["frames"]) == 3
    assert result["duration"] == 0.75
    assert all(len(frame) == 32 * 19 for frame in result["frames"])
    assert all(0 <= value < colors for frame in result["frames"] for value in frame)
    assert len(set(result["frames"][0])) > 1


def test_start_past_end(client, video):
    response = upload(client, video, start=2)
    assert response.status_code == 422
    assert "end of the video" in response.json()["detail"]


@pytest.mark.parametrize("options", [{"width": 161}, {"fps": 0}, {"duration": 31},
                                     {"start": -1}, {"palette": "invalid"},
                                     {"duration": "nan"}])
def test_parameter_validation(client, video, options):
    assert upload(client, video, **options).status_code == 422


def test_invalid_file(client):
    response = client.post("/api/convert", files={"file": ("bad.mp4", b"not a video")})
    assert response.status_code == 422
    assert "decoded" in response.json()["detail"]


def test_empty_file(client):
    response = client.post("/api/convert", files={"file": ("empty.mp4", b"")})
    assert response.status_code == 422


def test_request_limit_rejects_before_upload(client, monkeypatch):
    monkeypatch.setattr("backend.app.MAX_REQUEST_BYTES", 1024)
    response = client.post("/api/convert", files={"file": ("large.mp4", b"x" * 2048)})
    assert response.status_code == 413


def test_chunked_request_limit(client, monkeypatch):
    monkeypatch.setattr("backend.app.MAX_REQUEST_BYTES", 1024)
    body = (b'--test\r\nContent-Disposition: form-data; name="file"; filename="large.mp4"\r\n'
            b'Content-Type: video/mp4\r\n\r\n' + b'x' * 2048 + b'\r\n--test--\r\n')
    response = client.post(
        "/api/convert", headers={"Content-Type": "multipart/form-data; boundary=test"},
        content=(body[index:index + 100] for index in range(0, len(body), 100)))
    assert response.status_code == 413


def test_actual_frame_cap(client, video, monkeypatch):
    monkeypatch.setattr("backend.app.MAX_FRAMES", 3)
    response = upload(client, video, width=16, fps=10, duration=1)
    assert response.status_code == 200, response.text
    assert len(response.json()["frames"]) == 3
    assert response.json()["duration"] == 0.3


def test_tall_video_preserves_aspect(client, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required")
    target = tmp_path / "tall.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=red:size=32x160:rate=1:duration=1", "-c:v", "mpeg4", str(target)
    ], check=True, timeout=20)
    response = upload(client, target, width=64, fps=1)
    assert response.status_code == 200, response.text
    assert response.json()["width"] == 18
    assert response.json()["height"] == 90


def test_slot_limit(client, video):
    import backend.app as api
    old_value = api._slots._value
    try:
        api._slots._value = 0
        response = upload(client, video)
        assert response.status_code == 503
    finally:
        api._slots._value = old_value


def test_mono_matches_browser_and_cli_at_the_luma_boundary(monkeypatch, tmp_path):
    import backend.app as api

    metadata = {"streams": [{"width": 4, "height": 1}]}

    def decode(command, _timeout):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, json.dumps(metadata).encode(), b"")
        # The second pixel has luma 127.7874: rounding at 127.5 would be wrong.
        Path(command[-1]).write_bytes(bytes([0, 0, 0, 127, 128, 128, 128, 128, 128, 255, 255, 255]))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(api, "_run", decode)
    result = api.convert_video(tmp_path / "input", tmp_path / "raw", 4, 1, 1., 0., "mono")
    assert result["palette"] == ["#171c24", "#f8f4e9"]
    assert result["frames"] == [[0, 0, 1, 1]]


@pytest.mark.parametrize("rotation", ["inf", "-inf", "nan"])
@pytest.mark.parametrize("location", ["tags", "side_data_list"])
def test_nonfinite_rotation_is_a_metadata_error(monkeypatch, tmp_path, rotation, location):
    import backend.app as api

    stream = {"width": 4, "height": 1}
    stream[location] = ({"rotate": rotation} if location == "tags"
                        else [{"rotation": rotation}])
    monkeypatch.setattr(api, "_run", lambda *_: subprocess.CompletedProcess(
        [], 0, json.dumps({"streams": [stream]}).encode(), b""))
    with pytest.raises(HTTPException) as error:
        api.convert_video(tmp_path / "input", tmp_path / "raw", 4, 1, 1., 0., "mono")
    assert error.value.status_code == 422
    assert "metadata" in error.value.detail


@pytest.mark.parametrize("decoder_fails", [False, True])
def test_cancelled_conversion_retains_slot_and_files_until_decoder_finishes(monkeypatch, decoder_fails):
    import backend.app as api

    async def exercise():
        monkeypatch.setattr(api, "_slots", asyncio.Semaphore(2))
        release = threading.Event()
        paths = []
        files_preserved = []

        def decode(source, target, *_):
            target.write_bytes(b"decoded frame")
            paths.append((source, target))
            if not release.wait(5):
                raise RuntimeError("Test did not release decoder")
            files_preserved.append(source.exists() and target.exists())
            if decoder_fails:
                raise HTTPException(422, "Decoder failed after cancellation")
            return {"frames": []}

        monkeypatch.setattr(api, "convert_video", decode)
        uploads = [UploadFile(filename="clip.mp4", file=io.BytesIO(b"video")) for _ in range(3)]
        tasks = []
        try:
            for index in range(2):
                tasks.append(asyncio.create_task(api.convert(uploads[index], 48, 8, 1., 0., "color")))

                async def wait_started():
                    while len(paths) <= index:
                        await asyncio.sleep(.001)

                await asyncio.wait_for(wait_started(), 2)
            for _ in range(2):
                for task in tasks:
                    task.cancel()
                await asyncio.sleep(.01)

            assert all(not task.done() for task in tasks)
            assert api._slots.locked()
            assert all(source.exists() and target.exists() for source, target in paths)
            with pytest.raises(HTTPException) as rejected:
                await api.convert(uploads[2], 48, 8, 1., 0., "color")
            assert rejected.value.status_code == 503
        finally:
            release.set()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for upload_file in uploads:
                await upload_file.close()

        assert all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes)
        assert files_preserved == [True, True]
        assert api._slots._value == 2
        assert all(not source.exists() and not target.parent.exists() for source, target in paths)

    asyncio.run(exercise())
