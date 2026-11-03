"""
TubeGrab core: everything that talks to yt-dlp. No UI code here, so it can be tested on its own.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import DownloadCancelled, parse_bytes

APP_NAME = "TubeGrab"
APP_VERSION = "1.1.0"
# "owner/repo" on GitHub, used to tell users when a new release is out.
# The GitHub release workflow fills both of these in automatically for the .exe.
GITHUB_REPO = ""

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
DATA_DIR = Path(os.environ.get("APPDATA") or (Path.home() / ".config")) / APP_NAME
SETTINGS_FILE = DATA_DIR / "settings.json"
IS_WIN = os.name == "nt"
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# ----------------------------------------------------------------------------------- settings
DEFAULTS = {
    "theme": "System",             # System | Light | Dark
    "download_dir": str(Path.home() / "Downloads" / APP_NAME),
    "mode": "video",               # video | audio
    "video_quality": "best",       # best | 2160 | 1440 | 1080 | 720 | 480 | 360
    "video_container": "mp4",      # mp4 (plays everywhere) | mkv (keeps original streams)
    "audio_format": "mp3",         # mp3 | m4a | opus | flac | wav
    "audio_quality": "0",          # 0 = best VBR, or a fixed kbps
    "subtitles": True,
    "auto_subtitles": False,
    "sub_langs": "en.*",
    "embed_thumbnail": True,
    "embed_metadata": True,
    "embed_chapters": True,
    "sponsorblock": False,
    "skip_downloaded": True,
    "playlist_folder": True,
    "number_playlist_items": True,
    "concurrent_fragments": 4,
    "rate_limit": "",              # e.g. "2M" - empty means unlimited
    "cookies_browser": "",         # "" | firefox | chrome | edge | brave | opera | vivaldi | safari
}
CHOICES = {
    "theme": {"System", "Light", "Dark"},
    "mode": {"video", "audio"},
    "video_quality": {"best", "2160", "1440", "1080", "720", "480", "360"},
    "video_container": {"mp4", "mkv"},
    "audio_format": {"mp3", "m4a", "opus", "flac", "wav"},
    "audio_quality": {"0", "320", "256", "192", "128"},
    "cookies_browser": {"", "firefox", "chrome", "edge", "brave", "opera", "vivaldi", "safari"},
}
LIMITS = {"concurrent_fragments": (1, 16)}


def clean_settings(new: dict, base: dict | None = None) -> dict:
    """Merge `new` over `base` (or the defaults), keeping only known keys with valid values."""
    out = dict(base or DEFAULTS)
    for key, value in (new or {}).items():
        if key not in DEFAULTS:
            continue
        default = DEFAULTS[key]
        try:
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                lo, hi = LIMITS.get(key, (0, 10**6))
                value = max(lo, min(hi, int(value)))
            else:
                value = str(value).strip()
        except (TypeError, ValueError):
            continue
        if key in CHOICES and value not in CHOICES[key]:
            continue
        if key == "download_dir" and not value:
            continue
        out[key] = value
    return out


def load_settings() -> dict:
    try:
        return clean_settings(json.loads(SETTINGS_FILE.read_text("utf-8")))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(settings: dict):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(clean_settings(settings), indent=2), "utf-8")
    except OSError:
        pass


def audio_dir(settings: dict) -> Path:
    # Audio gets its own folder. Sharing one with videos is unsafe: yt-dlp would reuse an existing
    # "Title [id].mp4" as the source for the MP3 and then delete it after converting.
    return Path(settings["download_dir"]) / "Audio"


def history_files() -> list[Path]:
    return [DATA_DIR / f"archive-{m}.txt" for m in ("video", "audio")]


# ----------------------------------------------------------------------------------- tools
def _local_tool(name: str) -> str | None:
    exe = name + (".exe" if IS_WIN else "")
    for d in (APP_DIR, APP_DIR / "ffmpeg", APP_DIR / "ffmpeg" / "bin", APP_DIR / "bin", RES_DIR):
        if (d / exe).is_file():
            return str(d / exe)
    return shutil.which(name)


def find_ffmpeg_dir() -> str | None:
    ff = _local_tool("ffmpeg")
    if ff and _local_tool("ffprobe"):
        return str(Path(ff).parent)
    return None


def js_runtimes() -> dict:
    """yt-dlp needs a JavaScript runtime (Deno recommended) for full YouTube support."""
    return {n: {"path": p} for n in ("deno", "node", "bun") if (p := _local_tool(n))}


def ytdlp_version() -> str:
    return yt_dlp.version.__version__


# ----------------------------------------------------------------------------------- links
_URL = re.compile(r"(?:https?://|www\.|(?:m\.|music\.)?youtube\.com/|youtu\.be/)[^\s\"'<>,\]\[]+", re.I)


def extract_urls(text: str) -> list[str]:
    """Pull links out of any text (also bare 'youtu.be/x' / 'www.youtube.com/...'), de-duplicated."""
    out: list[str] = []
    for u in _URL.findall(text or ""):
        u = u.rstrip(").;")
        if not re.match(r"https?://", u, re.I):
            u = "https://" + u
        if u not in out:
            out.append(u)
    return out


def video_id_in_url(url: str) -> str | None:
    q = parse_qs(urlparse(url).query)
    return (q.get("v") or [None])[0]


def compress_ranges(numbers) -> str:
    """{1,2,3,5} -> '1-3,5' (yt-dlp --playlist-items syntax)."""
    nums = sorted(set(int(n) for n in numbers))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(out)


def base_opts(settings: dict) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "remote_components": ["ejs:github"]}
    if runtimes := js_runtimes():
        opts["js_runtimes"] = runtimes
    if settings.get("cookies_browser"):
        opts["cookiesfrombrowser"] = (settings["cookies_browser"],)
    return opts


def _thumb(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    return thumbs[-1]["url"] if thumbs else None


def analyze(url: str, settings: dict) -> dict:
    """Quickly read what a link is (video or playlist + its items) without downloading."""
    opts = base_opts(settings) | {"extract_flat": "in_playlist", "skip_download": True, "noplaylist": False,
                                  "logger": _QuietLogger()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("Nothing found at this link.")

    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        entries = []
        for i, e in enumerate(info.get("entries") or [], 1):
            e = e or {}
            entries.append({"index": i, "id": e.get("id"), "title": e.get("title") or e.get("id") or f"Item {i}",
                            "duration": e.get("duration")})
        return {"kind": "playlist", "url": url, "id": info.get("id"), "title": info.get("title") or "Playlist",
                "uploader": info.get("uploader") or info.get("channel") or "", "thumbnail": _thumb(info),
                "count": len(entries), "entries": entries, "single_id": video_id_in_url(url)}

    return {"kind": "video", "url": url, "id": info.get("id"), "title": info.get("title") or url,
            "uploader": info.get("uploader") or info.get("channel") or "", "thumbnail": _thumb(info),
            "duration": info.get("duration"), "count": 1}


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


# ----------------------------------------------------------------------------------- errors
HINTS = [
    ("sign in to confirm", "YouTube wants a logged-in session (age limit or bot check). In Settings, set "
                           "'Use cookies from browser' - Firefox works most reliably."),
    ("javascript runtime", "Install Deno (run Install-Tools.bat) so yt-dlp can solve YouTube's challenges."),
    ("challenge", "Install Deno and update yt-dlp - YouTube changed something."),
    ("http error 403", "YouTube refused the download. Updating yt-dlp usually fixes this."),
    ("requested format is not available", "That quality isn't available - try 'Best' or a lower resolution."),
    ("private video", "This video is private."),
    ("members-only", "This is members-only content; it needs cookies from an account that has access."),
    ("ffmpeg", "FFmpeg problem - make sure ffmpeg and ffprobe are installed (run Install-Tools.bat)."),
    ("could not copy", "Close the browser you picked for cookies (Chrome/Edge lock their cookie file), "
                       "or switch to Firefox."),
    ("unable to download webpage", "Couldn't reach the site - check the link and your internet connection."),
]


def hint_for(text: str) -> str:
    text = (text or "").lower()
    return next((hint for needle, hint in HINTS if needle in text), "")


def clean_error(text: str) -> str:
    text = ANSI.sub("", str(text)).strip()
    return text[len("ERROR:"):].strip() if text.startswith("ERROR:") else text


# ----------------------------------------------------------------------------------- downloading
PP_NAMES = {
    "FFmpegExtractAudio": "Converting audio",
    "FFmpegMerger": "Merging video + audio",
    "FFmpegVideoRemuxer": "Remuxing",
    "EmbedThumbnail": "Embedding cover",
    "FFmpegEmbedSubtitle": "Embedding subtitles",
    "FFmpegMetadata": "Writing metadata",
    "SponsorBlock": "Checking SponsorBlock",
    "ModifyChapters": "Cutting sponsor segments",
    "FFmpegThumbnailsConvertor": "Preparing cover",
    "MoveFiles": "Finishing",
}
_ARCHIVED = re.compile(r"\[download\] (?:([\w-]+): )?.*has already been recorded in the archive")
_ERR_ID = re.compile(r"^\[[\w:.-]+\] ([\w-]{6,}): ")


@dataclass
class Task:
    """One link to download. `items` is a yt-dlp playlist selection like '1-3,7' (None = all)."""
    url: str
    mode: str = "video"
    items: str | None = None
    noplaylist: bool = False
    title: str = ""


@dataclass
class Result:
    status: str = "done"                 # done | partial | error | cancelled
    files: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped: int = 0


Emit = Callable[[str, dict], None]


class _Logger:
    def __init__(self, emit: Emit, result: Result):
        self.emit, self.result = emit, result

    def debug(self, msg: str):
        m = _ARCHIVED.search(ANSI.sub("", msg))
        if m:
            self.result.skipped += 1
            self.emit("skipped", {"id": m.group(1)})

    info = debug

    def warning(self, msg: str):
        msg = ANSI.sub("", msg).replace("WARNING: ", "", 1).strip()
        if msg:
            self.emit("warning", {"message": msg})

    def error(self, msg: str):
        # yt-dlp also routes notices like "Deprecated Feature: ..." through here; only real errors count
        msg = ANSI.sub("", msg).strip()
        if not msg.startswith("ERROR:"):
            if msg:
                self.emit("warning", {"message": msg})
            return
        msg = clean_error(msg)[:600]
        if msg and msg not in self.result.errors:
            self.result.errors.append(msg)
            m = _ERR_ID.match(msg)
            self.emit("error", {"message": msg, "id": m.group(1) if m else None, "hint": hint_for(msg)})


def build_opts(task: Task, settings: dict) -> dict:
    """yt-dlp options for a task (hooks and logger are added by download())."""
    s = settings
    mode = task.mode
    name = "%(title)s [%(id)s].%(ext)s"
    if s["number_playlist_items"]:
        name = "%(playlist_index&{} - |)s" + name
    if s["playlist_folder"]:
        name = "%(playlist_title|.)s/" + name

    home = audio_dir(s) if mode == "audio" else Path(s["download_dir"])
    opts = base_opts(s) | {
        # half-finished files live in a hidden temp folder (per mode) instead of cluttering downloads
        "paths": {"home": str(home), "temp": str(Path(s["download_dir"]) / ".tubegrab-tmp" / mode)},
        "outtmpl": {"default": name},
        "windowsfilenames": True,
        "ignoreerrors": True,
        "noplaylist": task.noplaylist,
        "concurrent_fragment_downloads": s["concurrent_fragments"],
        "retries": 10,
        "fragment_retries": 10,
        "ffmpeg_location": find_ffmpeg_dir(),
    }
    if task.items:
        if not re.fullmatch(r"[0-9,\-: ]+", task.items):
            raise ValueError("Invalid item selection.")
        opts["playlist_items"] = task.items
    if s["skip_downloaded"]:
        # separate history per mode, so grabbing the MP3 of a video you already have still works
        opts["download_archive"] = str(DATA_DIR / f"archive-{mode}.txt")
    if s["rate_limit"] and (rl := parse_bytes(s["rate_limit"])):
        opts["ratelimit"] = rl

    pps = []
    if s["sponsorblock"]:
        cats = ["sponsor", "selfpromo", "interaction"]
        pps += [{"key": "SponsorBlock", "categories": cats, "when": "after_filter"},
                {"key": "ModifyChapters", "remove_sponsor_segments": cats}]

    if mode == "audio":
        opts["format"] = "bestaudio/best"
        pps.append({"key": "FFmpegExtractAudio", "preferredcodec": s["audio_format"],
                    "preferredquality": s["audio_quality"]})
    else:
        q = s["video_quality"]
        opts["format"] = "bv*+ba/b" if q == "best" else f"bv*[height<={q}]+ba/b[height<={q}]/bv*+ba/b"
        opts["merge_output_format"] = s["video_container"]
        if s["video_container"] == "mp4":
            # highest resolution first, then prefer H.264/AAC so the file plays everywhere
            opts["format_sort"] = ["res", "vcodec:h264", "acodec:aac"]
        if s["subtitles"]:
            langs = [x.strip() for x in s["sub_langs"].split(",") if x.strip()] or ["en.*"]
            opts.update(writesubtitles=True, writeautomaticsub=s["auto_subtitles"], subtitleslangs=langs)
            pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})

    if s["embed_metadata"] or s["embed_chapters"]:
        pps.append({"key": "FFmpegMetadata", "add_metadata": s["embed_metadata"],
                    "add_chapters": s["embed_chapters"]})
    if s["embed_thumbnail"] and not (mode == "audio" and s["audio_format"] == "wav"):
        opts["writethumbnail"] = True
        pps.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
        pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
    opts["postprocessors"] = pps
    return opts


def download(task: Task, settings: dict, emit: Emit, cancel: threading.Event | None = None,
             pause: threading.Event | None = None) -> Result:
    """
    Download one task. Calls emit(event, data) from this (worker) thread:
      item      {id, index, title}            a new video started
      progress  {id, fraction, speed, eta, downloaded, total}
      stage     {id, name}                    post-processing step (merging, converting...)
      file      {id, path}                    a finished file
      skipped   {id}                          already in the download history
      error     {message, id, hint}           warning   {message}
    `pause` set = hold the download until it is cleared; `cancel` set = stop.
    """
    cancel = cancel or threading.Event()
    pause = pause or threading.Event()
    result = Result()
    state = {"id": None}

    def wait_or_stop():
        while pause.is_set() and not cancel.is_set():
            time.sleep(0.2)
        if cancel.is_set():
            raise DownloadCancelled()

    def on_progress(d: dict):
        wait_or_stop()
        info = d.get("info_dict") or {}
        vid = info.get("id")
        if vid and vid != state["id"]:
            state["id"] = vid
            emit("item", {"id": vid, "index": info.get("playlist_index"), "title": info.get("title") or vid})
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                frac = (d.get("downloaded_bytes") or 0) / total
            elif d.get("fragment_count"):
                frac = (d.get("fragment_index") or 0) / d["fragment_count"]
            else:
                frac = None
            emit("progress", {"id": vid, "fraction": None if frac is None else max(0.0, min(frac, 1.0)),
                              "speed": d.get("speed"), "eta": d.get("eta"),
                              "downloaded": d.get("downloaded_bytes"), "total": total})

    def on_postprocess(d: dict):
        if cancel.is_set():
            raise DownloadCancelled()
        if d.get("status") == "started":
            emit("stage", {"id": (d.get("info_dict") or {}).get("id") or state["id"],
                           "name": PP_NAMES.get(d.get("postprocessor"), "Processing")})

    def on_file(path: str):
        result.files.append(path)
        emit("file", {"id": state["id"], "path": path})

    if not find_ffmpeg_dir():
        result.errors.append("FFmpeg / FFprobe not found.")
        emit("error", {"message": "FFmpeg / FFprobe not found.", "id": None,
                       "hint": "Install FFmpeg (run Install-Tools.bat), then restart TubeGrab."})
        result.status = "error"
        return result

    try:
        opts = build_opts(task, settings) | {
            "logger": _Logger(emit, result),
            "progress_hooks": [on_progress],
            "postprocessor_hooks": [on_postprocess],
            "post_hooks": [on_file],
        }
        Path(opts["paths"]["home"]).mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)   # holds the download history
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([task.url])
    except DownloadCancelled:
        pass
    except Exception as e:  # noqa: BLE001 - surface anything to the UI
        msg = clean_error(e)[:600]
        if msg not in result.errors:
            result.errors.append(msg)
            emit("error", {"message": msg, "id": state["id"], "hint": hint_for(msg)})

    if cancel.is_set():
        result.status = "cancelled"
    elif result.errors:
        result.status = "partial" if (result.files or result.skipped) else "error"
    return result


# ----------------------------------------------------------------------------------- updates
def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def check_for_update() -> dict | None:
    """Ask GitHub for the latest release; None if offline, not configured or already newest."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", GITHUB_REPO):
        return None
    import urllib.request
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.load(r)
        latest = str(data.get("tag_name") or "").lstrip("vV")
        if latest and _vtuple(latest) > _vtuple(APP_VERSION):
            return {"version": latest, "url": data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases"}
    except Exception:  # noqa: BLE001 - never bother the user about this
        pass
    return None


def update_ytdlp() -> tuple[bool, str]:
    if FROZEN:
        where = f"https://github.com/{GITHUB_REPO}/releases" if GITHUB_REPO else "build-exe.bat"
        return False, f"This .exe has yt-dlp built in.\nGet the newest TubeGrab from {where}."
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                       capture_output=True, text=True,
                       creationflags=0x08000000 if IS_WIN else 0)
    if r.returncode == 0:
        return True, "yt-dlp updated. Close TubeGrab and start it again to use the new version."
    return False, (r.stderr or r.stdout)[-800:]


# ----------------------------------------------------------------------------------- helpers
def fmt_duration(s) -> str:
    if s is None or s == "":
        return ""
    s = int(round(float(s)))
    h, m, x = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def fmt_bytes(n) -> str:
    if not n:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def open_path(path: str | Path):
    p = Path(path)
    if IS_WIN:
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
