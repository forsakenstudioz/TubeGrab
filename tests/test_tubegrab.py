"""Smoke tests: run with `python -m pytest -q` (needs yt-dlp and ffmpeg installed)."""
import functools
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="tubegrab-test-"))
os.environ["APPDATA"] = str(TMP / "appdata")          # keep test settings away from the real ones
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tubegrab as t  # noqa: E402
import yt_dlp  # noqa: E402


def test_settings_are_validated():
    s = t.clean_settings({"max_parallel": 99, "mode": "nonsense", "video_quality": "720", "unknown": 1})
    assert s["max_parallel"] == 5
    assert s["mode"] == t.DEFAULTS["mode"]
    assert s["video_quality"] == "720"
    assert "unknown" not in s


@pytest.mark.parametrize("mode,container,subs,sponsor,thumb,afmt", list(itertools.product(
    ["video", "audio"], ["mp4", "mkv"], [True, False], [True, False], [True, False], ["mp3", "wav"])))
def test_every_option_combo_is_accepted_by_ytdlp(mode, container, subs, sponsor, thumb, afmt):
    job = t.new_job({"url": "https://youtu.be/x", "mode": mode, "items": "1-3,5"})
    job["settings"] = dict(t.DEFAULTS, video_container=container, subtitles=subs, sponsorblock=sponsor,
                           embed_thumbnail=thumb, audio_format=afmt, rate_limit="2M", video_quality="1080")
    with yt_dlp.YoutubeDL(t.build_opts(job)):
        pass


def test_bad_item_selection_is_rejected():
    with pytest.raises(ValueError):
        t.new_job({"url": "https://youtu.be/x", "items": "1; rm -rf"})


def test_notices_are_not_counted_as_errors():
    job = t.new_job({"url": "https://youtu.be/x"})
    log = t.JobLogger(job)
    log.error("Deprecated Feature: Support for Python version 3.10 has been deprecated.")
    log.error("\x1b[0;31mERROR:\x1b[0m [youtube] x: Video unavailable")
    assert job["errors"] == ["[youtube] x: Video unavailable"]


def test_version_compare():
    assert t._vtuple("1.10.0") > t._vtuple("1.9.3")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_end_to_end_video_then_audio_keeps_both_files():
    media = TMP / "media"
    media.mkdir()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "5", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(media / "sample.mp4")], check=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(media)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/sample.mp4"
    out = TMP / "downloads"
    try:
        for mode in ("video", "audio"):
            job = t.new_job({"url": url, "mode": mode})
            job["settings"] = dict(t.DEFAULTS, download_dir=str(out), embed_thumbnail=False, skip_downloaded=False)
            t.run_job(job)
            assert job["status"] == "done", job["errors"]
    finally:
        server.shutdown()
    assert (out / "sample [sample].mp4").is_file()
    assert (out / "Audio" / "sample [sample].mp3").is_file()
