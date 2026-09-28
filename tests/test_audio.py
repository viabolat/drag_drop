"""Optional MP3 soundtrack: ffmpeg graph shape, bad-audio fallback, and endpoint plumbing.
Hermetic — ffmpeg is mocked, so these assert the command, not a real mux."""
import io
import json
import os
import shutil
import subprocess

import compositor
from app import UPLOAD_DIR


def _frames(tmp_path, n=3):
    return [str(tmp_path / f"f{i}.jpg") for i in range(n)]


def test_video_duration_accounts_for_crossfades():
    assert compositor._video_duration(1) == compositor.HOLD_SECONDS
    assert compositor._video_duration(4) == round(4 * 4.0 - 3 * 0.7, 3)


def test_build_mp4_without_audio_is_silent(tmp_path, mock_ffmpeg_success):
    assert compositor._build_mp4(_frames(tmp_path), str(tmp_path / "o.mp4"))
    cmd = mock_ffmpeg_success.call_args.args[0]
    assert "-an" in cmd and "[aout]" not in cmd


def test_build_mp4_with_audio_loops_trims_and_fades(tmp_path, mock_ffmpeg_success):
    frames = _frames(tmp_path, 3)
    assert compositor._build_mp4(frames, str(tmp_path / "o.mp4"), audio_path="song.mp3")
    cmd = mock_ffmpeg_success.call_args.args[0]
    i = cmd.index("song.mp3")
    assert cmd[i - 3:i] == ["-stream_loop", "-1", "-i"]
    graph = cmd[cmd.index("-filter_complex") + 1]
    dur = compositor._video_duration(3)
    assert f"[3:a]atrim=0:{dur}" in graph and "afade=t=out" in graph
    assert "-an" not in cmd
    assert cmd[cmd.index("[aout]") - 1] == "-map"


def test_bad_audio_falls_back_to_silent_mp4(tmp_path, mocker, make_jpeg_bytes):
    mocker.patch("compositor.shutil.which", return_value="/usr/bin/ffmpeg")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "-an" not in cmd:  # the audio attempt fails, the silent retry succeeds
            raise subprocess.CalledProcessError(1, cmd)

    mocker.patch("compositor.subprocess.run", side_effect=fake_run)
    img = tmp_path / "a.jpg"
    img.write_bytes(make_jpeg_bytes().read())
    audio = tmp_path / "bad.mp3"
    audio.write_bytes(b"not audio")
    out = compositor.render_post_package([{"path": str(img), "kicker": "", "headline": "", "sub": ""}],
                                         output_base_name="test_audio_fallback", audio_path=str(audio))
    try:
        assert out["mp4"] is not None and out["audio"] is False
        assert len(calls) == 2 and "-an" in calls[1]
    finally:
        shutil.rmtree(os.path.dirname(out["pdf"]))


def test_generate_post_passes_audio_and_cleans_up(client, mocker, make_jpeg_bytes):
    captured = {}

    def fake_render(dataset, output_base_name=None, audio_path=None, **kw):
        captured["audio_path"] = audio_path
        captured["audio_bytes"] = open(audio_path, "rb").read()
        return {"mp4": "o.mp4", "pdf": "o.pdf", "audio": True}

    mocker.patch("app.render_post_package", side_effect=fake_render)
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_audio", "metadata_json": json.dumps([{"kicker": "", "headline": "", "sub": ""}])},
        files=[("files", ("a.jpg", make_jpeg_bytes(), "image/jpeg")),
               ("audio", ("song.mp3", io.BytesIO(b"ID3fake"), "audio/mpeg"))],
    )
    assert resp.status_code == 200
    assert os.path.basename(captured["audio_path"]) == "song.mp3"
    assert captured["audio_bytes"] == b"ID3fake"
    assert not os.path.exists(captured["audio_path"])  # temp soundtrack deleted after render
    assert not os.path.exists(os.path.join(UPLOAD_DIR, "audio"))  # per-upload subdir pruned too


def test_generate_post_reports_dropped_soundtrack(client, mocker, make_jpeg_bytes):
    mocker.patch("app.render_post_package", return_value={"mp4": "o.mp4", "pdf": "o.pdf", "audio": False})
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_audio", "metadata_json": json.dumps([{"kicker": "", "headline": "", "sub": ""}])},
        files=[("files", ("a.jpg", make_jpeg_bytes(), "image/jpeg")),
               ("audio", ("bad.mp3", io.BytesIO(b"x"), "audio/mpeg"))],
    )
    assert resp.status_code == 200
    assert "without audio" in resp.json()["message"]


def test_generate_post_without_audio_passes_none(client, mocker, make_jpeg_bytes):
    captured = {}

    def fake_render(dataset, output_base_name=None, audio_path="unset", **kw):
        captured["audio_path"] = audio_path
        return {"mp4": "o.mp4", "pdf": "o.pdf", "audio": False}

    mocker.patch("app.render_post_package", side_effect=fake_render)
    resp = client.post(
        "/generate-post/",
        data={"output_name": "test_audio", "metadata_json": json.dumps([{"kicker": "", "headline": "", "sub": ""}])},
        files=[("files", ("a.jpg", make_jpeg_bytes(), "image/jpeg"))],
    )
    assert resp.status_code == 200 and captured["audio_path"] is None
    assert "without audio" not in resp.json()["message"]
