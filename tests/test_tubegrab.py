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



def test_csv_with_folder_column():
    csv_text = ("\ufefflink,folder number\n"
                "https://youtu.be/aaa,1\n"
                "https://www.youtube.com/watch?v=bbb&list=PL1 , 2\n"
                "\"https://youtu.be/ccc\",\n"            # old links.txt style: no folder
                "https://youtu.be/aaa,1\n"                 # duplicate row
                "https://youtu.be/aaa,2\n")                # same video, other folder
    assert core.parse_links(csv_text) == [
        ("https://youtu.be/aaa", "1"), ("https://www.youtube.com/watch?v=bbb&list=PL1", "2"),
        ("https://youtu.be/ccc", None), ("https://youtu.be/aaa", "2")]


def test_folder_column_found_by_header_and_other_separators():
    assert core.parse_links("title;Folder;url\nMy song;7;https://youtu.be/x") == [("https://youtu.be/x", "7")]
    assert core.parse_links("youtu.be/d\t3") == [("https://youtu.be/d", "3")]          # pasted from Excel
    assert core.parse_links("see youtu.be/a and youtu.be/b") == [("https://youtu.be/a", None),
                                                                 ("https://youtu.be/b", None)]


def test_semicolon_inside_a_title_does_not_break_the_row():
    text = ('Folder no,Video No,Video Title,YouTube Link,Note\n'
            '3,8,Part 2; revision,https://youtu.be/waL-wFNi_mE,\n'
            '15,1,"MATHS - TEST, part 1",https://youtu.be/KVDXXXCwnKY,Same video as course 16\n')
    assert core.parse_links(text) == [("https://youtu.be/waL-wFNi_mE", "3"), ("https://youtu.be/KVDXXXCwnKY", "15")]


def test_video_number_column_is_read():
    text = ("Folder no,Video No,Video Title,YouTube Link,Note\n"
            "3,1,Intro,https://youtu.be/Os-FdeE6dhg,\n"
            "3,2,Intro again,https://youtu.be/Os-FdeE6dhg,Repeat of video 1\n"
            "3,8,Part 2,https://youtu.be/waL-wFNi_mE,\n")
    assert core.parse_link_rows(text) == [
        {"url": "https://youtu.be/Os-FdeE6dhg", "folder": "3", "number": 1, "title": "Intro"},
        {"url": "https://youtu.be/waL-wFNi_mE", "folder": "3", "number": 8, "title": "Part 2"}]
    assert core.parse_link_rows("Note,link\nhello,https://youtu.be/a")[0]["number"] is None   # "Note" isn't "No"
    assert core.number_prefix(8, 15) == "08" and core.number_prefix(7, 125) == "007" and core.number_prefix(None, 9) is None


def test_preview_names_match_the_download_template():
    s = dict(core.DEFAULTS, download_dir="/x/TubeGrab")
    namer = core.FileNamer(s)
    assert namer.path("video", "3", "sollum porulum  2", "waL-wFNi_mE", prefix="08").as_posix() == \
        "3/08 - sollum porulum  2 [waL-wFNi_mE].mp4"
    assert namer.path("audio", "3", "A/B: why?", "abc").as_posix() == "3/Audio/A⧸B： why？ [abc].mp3"


def test_folder_names_are_made_safe():
    assert core.clean_folder("1.0") == "1"
    assert core.clean_folder(" .. ") is None
    assert core.clean_folder("a/b") == "a_b"
    assert core.clean_folder("..\\..\\Windows") == "_.._Windows"
    assert core.clean_folder("CON") == "CON_"
    assert core.clean_folder('"Songs"') == "Songs"


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


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_end_to_end_videos_go_into_their_folders():
    media = TMP / "media2"
    media.mkdir()
    for name in ("a", "b"):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                        "-f", "lavfi", "-i", "sine", "-t", "2", "-c:v", "libx264", "-c:a", "aac", "-shortest",
                        str(media / f"{name}.mp4")], check=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(media)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    out = TMP / "foldered"
    s = dict(core.DEFAULTS, download_dir=str(out), embed_thumbnail=False)
    rows = core.parse_link_rows(f"Folder,No,link\n1,1,{base}/a.mp4\n2,1,{base}/b.mp4\n2,2,{base}/a.mp4\n")
    namer = core.FileNamer(s)
    try:
        for r0 in rows:
            prefix = core.number_prefix(r0["number"], 2)
            r = core.download(core.Task(r0["url"], "video", subfolder=r0["folder"], prefix=prefix), s, lambda k, d: None)
            assert r.status == "done" and r.files, r.errors
            vid = r0["url"].rsplit("/", 1)[1][:-4]
            assert Path(r.files[0]) == out / namer.path("video", r0["folder"], vid, vid, prefix=prefix)
        r = core.download(core.Task(f"{base}/b.mp4", "audio", subfolder="2"), s, lambda k, d: None)
        assert r.status == "done", r.errors
    finally:
        server.shutdown()
    assert (out / "1" / "01 - a [a].mp4").is_file()
    assert (out / "2" / "01 - b [b].mp4").is_file()
    assert (out / "2" / "02 - a [a].mp4").is_file()     # same video in a second folder is not skipped
    assert (out / "2" / "Audio" / "b [b].mp3").is_file()
    opts = core.build_opts(core.Task("https://youtu.be/x", subfolder="1"), s)
    assert "playlist_title" not in opts["outtmpl"]["default"]          # playlist videos go straight into "1"


def test_single_video_links_need_no_reading():
    assert core.single_video_id("https://youtu.be/waL-wFNi_mE") == "waL-wFNi_mE"
    assert core.single_video_id("https://www.youtube.com/watch?v=waL-wFNi_mE") == "waL-wFNi_mE"
    assert core.single_video_id("https://www.youtube.com/shorts/waL-wFNi_mE") == "waL-wFNi_mE"
    assert core.single_video_id("https://www.youtube.com/watch?v=waL-wFNi_mE&list=PL1") is None   # pick from list
    assert core.single_video_id("https://www.youtube.com/playlist?list=PL1") is None
    assert core.single_video_id("https://www.youtube.com/@channel") is None


def test_youtube_rate_limit_is_not_a_failure():
    msg = ("[youtube] h_oaSE35uUI: Video unavailable. This content isn't available, try again later. "
           "Your account has been rate-limited by YouTube for up to an hour.")
    assert core.is_rate_limited(msg) and core.is_rate_limited("HTTP Error 429: Too Many Requests")
    assert not core.is_rate_limited("Private video") and not core.is_rate_limited("Video unavailable")
    assert "waits" in core.hint_for(msg)
    # A rate-limit error stops the task right away and is reported as "rate_limited", not as an error.
    # (a local 404 stands in for YouTube's answer)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(TMP)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    original = core.is_rate_limited
    core.is_rate_limited = lambda text: "404" in (text or "") or original(text)
    events = []
    try:
        r = core.download(core.Task(f"http://127.0.0.1:{server.server_address[1]}/missing.mp4"),
                          dict(core.DEFAULTS, download_dir=str(TMP / "rl"), pacing="off"),
                          lambda k, d: events.append(k))
    finally:
        core.is_rate_limited = original
        server.shutdown()
    assert r.status == "rate_limited" and r.rate_limited and not r.errors and "error" not in events


def test_pacing_settings():
    o = core.build_opts(core.Task("https://youtu.be/x"), dict(core.DEFAULTS))
    assert (o["sleep_interval"], o["max_sleep_interval"]) == (4, 10)
    o = core.build_opts(core.Task("https://youtu.be/x"), dict(core.DEFAULTS, pacing="safe"))
    assert (o["sleep_interval"], o["max_sleep_interval"]) == (10, 20)
    assert "sleep_interval" not in core.build_opts(core.Task("https://youtu.be/x"), dict(core.DEFAULTS, pacing="off"))
