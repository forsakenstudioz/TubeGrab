"""Tests for the download logic: run with `python -m pytest -q` (needs yt-dlp; the last test also needs ffmpeg)."""
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

import tubegrab_core as core  # noqa: E402
import yt_dlp  # noqa: E402


def test_settings_are_validated():
    s = core.clean_settings({"concurrent_fragments": 99, "mode": "nonsense", "video_quality": "720", "unknown": 1})
    assert s["concurrent_fragments"] == 16
    assert s["mode"] == core.DEFAULTS["mode"]
    assert s["video_quality"] == "720"
    assert "unknown" not in s


def test_links_are_found_in_any_text():
    text = "watch youtu.be/abc), then https://x.com/a; and www.youtube.com/watch?v=1&list=2 twice youtu.be/abc"
    assert core.extract_urls(text) == ["https://youtu.be/abc", "https://x.com/a",
                                       "https://www.youtube.com/watch?v=1&list=2"]
    assert core.video_id_in_url("https://www.youtube.com/watch?v=xyz&list=PL1") == "xyz"


def test_playlist_ranges():
    assert core.compress_ranges([9, 1, 2, 3, 5, 8]) == "1-3,5,8-9"


@pytest.mark.parametrize("mode,container,subs,sponsor,thumb,afmt", list(itertools.product(
    ["video", "audio"], ["mp4", "mkv"], [True, False], [True, False], [True, False], ["mp3", "wav"])))
def test_every_option_combo_is_accepted_by_ytdlp(mode, container, subs, sponsor, thumb, afmt):
    task = core.Task("https://youtu.be/x", mode, items="1-3,5")
    s = dict(core.DEFAULTS, video_container=container, subtitles=subs, sponsorblock=sponsor,
             embed_thumbnail=thumb, audio_format=afmt, rate_limit="2M", video_quality="1080")
    with yt_dlp.YoutubeDL(core.build_opts(task, s)):
        pass


def test_bad_item_selection_is_rejected():
    with pytest.raises(ValueError):
        core.build_opts(core.Task("https://youtu.be/x", items="1; rm -rf"), dict(core.DEFAULTS))


def test_notices_are_not_counted_as_errors():
    result, events = core.Result(), []
    log = core._Logger(lambda k, d: events.append((k, d)), result)
    log.error("Deprecated Feature: Support for Python version 3.10 has been deprecated.")
    log.error("\x1b[0;31mERROR:\x1b[0m [youtube] abcdefghijk: Video unavailable")
    log.debug("[download] abcdefghijk: Some title has already been recorded in the archive")
    assert result.errors == ["[youtube] abcdefghijk: Video unavailable"]
    assert ("error", {"message": "[youtube] abcdefghijk: Video unavailable", "id": "abcdefghijk",
                      "hint": ""}) in events
    assert result.skipped == 1 and ("skipped", {"id": "abcdefghijk"}) in events


def test_error_hints():
    assert "cookies" in core.hint_for("Sign in to confirm you're not a bot")
    assert core.hint_for("something new") == ""


def test_version_compare():
    assert core._vtuple("1.10.0") > core._vtuple("1.9.3")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_end_to_end_playlist_selection_audio_and_history():
    media = TMP / "media"
    media.mkdir()
    for i in (1, 2, 3):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                        "-f", "lavfi", "-i", f"sine=frequency={300 * i}", "-t", "3", "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", str(media / f"lesson{i}.mp4")], check=True)
    (media / "course.html").write_text("<html><head><title>Course</title></head><body>"
                                       + "".join(f'<video src="lesson{i}.mp4"></video>' for i in (1, 2, 3))
                                       + "</body></html>")
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(media)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    out = TMP / "downloads"
    s = dict(core.DEFAULTS, download_dir=str(out), embed_thumbnail=False)
    try:
        info = core.analyze(f"{base}/course.html", s)
        assert info["kind"] == "playlist" and info["count"] == 3

        events = []
        r = core.download(core.Task(f"{base}/course.html", "video", items="1,3"), s,
                          lambda k, d: events.append((k, d)))
        assert r.status == "done", r.errors
        assert sorted(p.name for p in (out / "Course").iterdir()) == \
            ["1 - Course (1) [course-1].mp4", "3 - Course (3) [course-3].mp4"]
        assert {d["index"] for k, d in events if k == "item"} == {1, 3}

        r = core.download(core.Task(f"{base}/lesson2.mp4", "audio"), s, lambda k, d: None)
        assert r.status == "done", r.errors
        assert (out / "Audio" / "lesson2 [lesson2].mp3").is_file()

        r = core.download(core.Task(f"{base}/lesson2.mp4", "audio"), s, lambda k, d: None)
        assert r.status == "done" and r.skipped == 1 and not r.files      # remembered in the history
    finally:
        server.shutdown()

