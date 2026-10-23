#!/usr/bin/env python3
"""
TubeGrab - a friendly downloader UI built on yt-dlp.

Run it with:   python tubegrab.py
It opens in your browser at http://127.0.0.1:8765 (only reachable from this PC).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, parse_bytes
except ImportError:
    print("yt-dlp is not installed.\nInstall it with:  python -m pip install -U \"yt-dlp[default]\"")
    input("Press Enter to exit...")
    sys.exit(1)

APP_NAME = "TubeGrab"
APP_VERSION = "1.0.0"
# "owner/repo" on GitHub, used to tell users when a new release is out.
# The GitHub release workflow fills both of these in automatically for the .exe.
GITHUB_REPO = ""
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
DATA_DIR = Path(os.environ.get("APPDATA") or (Path.home() / ".config")) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"
IS_WIN = os.name == "nt"
TOKEN = secrets.token_urlsafe(24)
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# --------------------------------------------------------------------------- settings
DEFAULTS = {
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
    "max_parallel": 2,
    "concurrent_fragments": 4,
    "rate_limit": "",              # e.g. "2M" - empty means unlimited
    "cookies_browser": "",         # "" | firefox | chrome | edge | brave | opera | vivaldi
}
CHOICES = {
    "mode": {"video", "audio"},
    "video_quality": {"best", "2160", "1440", "1080", "720", "480", "360"},
    "video_container": {"mp4", "mkv"},
    "audio_format": {"mp3", "m4a", "opus", "flac", "wav"},
    "audio_quality": {"0", "320", "256", "192", "128"},
    "cookies_browser": {"", "firefox", "chrome", "edge", "brave", "opera", "vivaldi"},
}
LIMITS = {"max_parallel": (1, 5), "concurrent_fragments": (1, 16)}

LOCK = threading.RLock()
SETTINGS: dict = dict(DEFAULTS)
JOBS: dict[str, dict] = {}


def clean_settings(new: dict) -> dict:
    out = dict(SETTINGS)
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


def load_settings():
    global SETTINGS
    try:
        SETTINGS = clean_settings(json.loads(SETTINGS_FILE.read_text("utf-8")))
    except (OSError, ValueError):
        SETTINGS = dict(DEFAULTS)


def save_settings(new: dict):
    global SETTINGS
    with LOCK:
        SETTINGS = clean_settings(new)
        SETTINGS_FILE.write_text(json.dumps(SETTINGS, indent=2), "utf-8")


# --------------------------------------------------------------------------- environment checks
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
    found = {}
    for name in ("deno", "node", "bun"):
        path = _local_tool(name)
        if path:
            found[name] = {"path": path}
    return found


UPDATE: dict = {}


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def check_for_update():
    """Ask GitHub for the latest release once at startup; silent if offline or not configured."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", GITHUB_REPO):
        return
    import urllib.request
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json", "User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.load(r)
        latest = str(data.get("tag_name") or "").lstrip("vV")
        if latest and _vtuple(latest) > _vtuple(APP_VERSION):
            UPDATE.update(version=latest, url=data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases")
    except Exception:  # noqa: BLE001 - never bother the user about this
        pass


def environment() -> dict:
    return {
        "app_version": APP_VERSION,
        "update": UPDATE or None,
        "repo": GITHUB_REPO or None,
        "ytdlp_version": yt_dlp.version.__version__,
        "ffmpeg": bool(find_ffmpeg_dir()),
        "js_runtime": next(iter(js_runtimes()), None),
        "frozen": FROZEN,
        "windows": IS_WIN,
    }


# --------------------------------------------------------------------------- analysis
def base_opts(settings: dict) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True,
            "remote_components": ["ejs:github"]}
    runtimes = js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    if settings.get("cookies_browser"):
        opts["cookiesfrombrowser"] = (settings["cookies_browser"],)
    return opts


def best_thumb(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    return thumbs[-1]["url"] if thumbs else None


def analyze(url: str) -> dict:
    with LOCK:
        settings = dict(SETTINGS)
    opts = base_opts(settings) | {"extract_flat": "in_playlist", "skip_download": True, "noplaylist": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("Nothing found at this link.")

    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        entries = []
        for i, e in enumerate(info.get("entries") or [], 1):
            e = e or {}
            entries.append({
                "index": i,
                "title": e.get("title") or e.get("id") or f"Item {i}",
                "duration": e.get("duration"),
            })
        thumb = best_thumb(info)
        if not thumb:
            for e in info.get("entries") or []:
                if e and (thumb := best_thumb(e)):
                    break
        q = urlparse(url).query
        return {
            "kind": "playlist",
            "title": info.get("title") or "Playlist",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "thumbnail": thumb,
            "count": len(entries),
            "entries": entries,
            # A watch?v=...&list=... link can mean "this video" or "the whole playlist"
            "has_single": bool(re.search(r"(^|&)v=", q)),
        }

    return {
        "kind": "video",
        "title": info.get("title") or url,
        "uploader": info.get("uploader") or info.get("channel") or "",
        "thumbnail": best_thumb(info),
        "duration": info.get("duration"),
        "count": 1,
    }


# --------------------------------------------------------------------------- downloading
PP_NAMES = {
    "FFmpegExtractAudio": "Converting audio",
    "FFmpegMerger": "Merging video + audio",
    "FFmpegVideoRemuxer": "Remuxing",
    "EmbedThumbnail": "Embedding cover art",
    "FFmpegEmbedSubtitle": "Embedding subtitles",
    "FFmpegMetadata": "Writing metadata",
    "SponsorBlock": "Checking SponsorBlock",
    "ModifyChapters": "Cutting sponsor segments",
    "FFmpegThumbnailsConvertor": "Preparing thumbnail",
    "MoveFiles": "Finishing",
}

HINTS = [
    ("sign in to confirm", "YouTube wants a logged-in session (age limit or bot check). In Settings, pick "
                           "'Use cookies from browser' - Firefox works most reliably."),
    ("javascript runtime", "Install Deno (see the banner at the top) so yt-dlp can solve YouTube's challenges."),
    ("challenge", "Install Deno and update yt-dlp - YouTube changed something."),
    ("http error 403", "YouTube refused the download. Updating yt-dlp usually fixes this."),
    ("requested format is not available", "That quality isn't available - try 'Best' or a lower resolution."),
    ("private video", "This video is private."),
    ("members-only", "This is members-only content; it needs cookies from an account that has access."),
    ("ffmpeg", "FFmpeg problem - make sure ffmpeg and ffprobe are installed."),
    ("could not copy", "Close the browser you picked for cookies (Chrome/Edge lock their cookie file), "
                       "or switch to Firefox."),
]


def hint_for(errors: list[str]) -> str:
    text = " ".join(errors).lower()
    for needle, hint in HINTS:
        if needle in text:
            return hint
    return ""


class JobLogger:
    def __init__(self, job: dict):
        self.job = job

    def debug(self, msg: str):
        if "has already been recorded in the archive" in msg:
            self.job["skipped"] += 1

    info = debug

    def warning(self, msg: str):
        pass

    def error(self, msg: str):
        # yt-dlp also routes notices like "Deprecated Feature: ..." through here; only real errors count
        msg = ANSI.sub("", msg).strip()
        if not msg.startswith("ERROR:"):
            return
        msg = msg[len("ERROR:"):].strip()
        if msg and msg not in self.job["errors"]:
            self.job["errors"].append(msg[:500])


def on_progress(job: dict, d: dict):
    if job["cancel"]:
        raise DownloadCancelled()
    info = d.get("info_dict") or {}
    if info.get("n_entries"):
        job["total"] = info["n_entries"]
    if info.get("playlist_autonumber"):
        job["item"] = info["playlist_autonumber"]
    if info.get("title"):
        job["current"] = info["title"]
    if d["status"] == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            frac = (d.get("downloaded_bytes") or 0) / total
        elif d.get("fragment_count"):
            frac = (d.get("fragment_index") or 0) / d["fragment_count"]
        else:
            frac = job["file_progress"]
        job.update(status="downloading", stage="Downloading", file_progress=max(0.0, min(frac, 1.0)),
                   speed=d.get("speed"), eta=d.get("eta"))
    elif d["status"] == "finished":
        job.update(file_progress=1.0, speed=None, eta=None)


def on_postprocess(job: dict, d: dict):
    if job["cancel"]:
        raise DownloadCancelled()
    if d.get("status") == "started":
        job.update(status="processing", stage=PP_NAMES.get(d.get("postprocessor"), "Processing"),
                   speed=None, eta=None)


def build_opts(job: dict) -> dict:
    s = job["settings"]
    mode = job["mode"]

    name = "%(title)s [%(id)s].%(ext)s"
    if s["number_playlist_items"]:
        name = "%(playlist_index&{} - |)s" + name
    if s["playlist_folder"]:
        name = "%(playlist_title|.)s/" + name

    # Audio goes to its own "Audio" folder. Sharing a folder with videos is unsafe: yt-dlp would reuse an
    # existing "Title [id].mp4" as the source for the MP3 and then delete it after converting.
    home = Path(s["download_dir"]) / "Audio" if mode == "audio" else Path(s["download_dir"])
    opts = base_opts(s) | {
        # half-finished files live in a hidden temp folder (per mode) instead of cluttering downloads
        "paths": {"home": str(home), "temp": str(Path(s["download_dir"]) / ".tubegrab-tmp" / mode)},
        "outtmpl": {"default": name},
        "windowsfilenames": True,
        "ignoreerrors": True,
        "logger": JobLogger(job),
        "progress_hooks": [lambda d: on_progress(job, d)],
        "postprocessor_hooks": [lambda d: on_postprocess(job, d)],
        "post_hooks": [lambda path: job["files"].append(path)],
        "noplaylist": job["noplaylist"],
        "concurrent_fragment_downloads": s["concurrent_fragments"],
        "retries": 10,
        "fragment_retries": 10,
        "ffmpeg_location": find_ffmpeg_dir(),
    }
    if job["items"]:
        opts["playlist_items"] = job["items"]
    if s["skip_downloaded"]:
        # separate archives so grabbing the MP3 of a video you already have still works
        opts["download_archive"] = str(DATA_DIR / f"archive-{mode}.txt")
    if s["rate_limit"]:
        rl = parse_bytes(s["rate_limit"])
        if rl:
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


def run_job(job: dict):
    job.update(status="starting", stage="Starting", started=time.time())
    if not find_ffmpeg_dir():
        job["errors"].append("FFmpeg / FFprobe not found.")
        job.update(status="error", hint="Install FFmpeg (see the banner at the top), then press Retry.")
        return
    try:
        Path(job["settings"]["download_dir"]).mkdir(parents=True, exist_ok=True)
        with yt_dlp.YoutubeDL(build_opts(job)) as ydl:
            ydl.download([job["url"]])
    except DownloadCancelled:
        pass
    except Exception as e:  # noqa: BLE001 - surface anything to the UI
        job["errors"].append(ANSI.sub("", str(e))[:500])

    if job["cancel"]:
        status = "cancelled"
    elif job["errors"]:
        status = "partial" if (job["files"] or job["skipped"]) else "error"
    else:
        status = "done"
    job.update(status=status, stage="", speed=None, eta=None, finished=time.time(), hint=hint_for(job["errors"]))


ACTIVE = {"starting", "downloading", "processing"}


def dispatcher():
    while True:
        with LOCK:
            running = sum(1 for j in JOBS.values() if j["status"] in ACTIVE)
            for job in sorted(JOBS.values(), key=lambda j: j["created"]):
                if running >= SETTINGS["max_parallel"]:
                    break
                if job["status"] == "queued":
                    job["status"] = "starting"
                    running += 1
                    threading.Thread(target=run_job, args=(job,), daemon=True).start()
        time.sleep(0.4)


def new_job(data: dict) -> dict:
    with LOCK:
        settings = dict(SETTINGS)
    mode = data.get("mode") if data.get("mode") in ("video", "audio") else settings["mode"]
    items = str(data.get("items") or "").strip()
    if items and not re.fullmatch(r"[0-9,\-: ]+", items):
        raise ValueError("Invalid item selection.")
    job = {
        "id": uuid.uuid4().hex[:10], "url": str(data["url"]).strip(),
        "title": str(data.get("title") or data["url"])[:300], "thumbnail": data.get("thumbnail"),
        "kind": data.get("kind") or "video", "mode": mode, "items": items or None,
        "noplaylist": bool(data.get("noplaylist")), "settings": settings, "created": time.time(),
        "expected": int(data["expected"]) if str(data.get("expected") or "").isdigit() else None,
    }
    reset_job(job)
    return job


def reset_job(job: dict):
    job.update(status="queued", stage="Waiting", cancel=False, item=1,
               total=job.get("expected") or None, file_progress=0.0, speed=None, eta=None,
               current="", files=[], errors=[], skipped=0, hint="", started=None, finished=None)


def public_job(job: dict) -> dict:
    total = job["total"] or 1
    item = min(job["item"] or 1, total)
    if job["status"] in ("done", "partial"):
        pct = 100.0
    else:
        pct = ((item - 1) + job["file_progress"]) / total * 100
    keys = ("id", "url", "title", "thumbnail", "kind", "mode", "items", "status", "stage", "item", "total",
            "speed", "eta", "current", "errors", "skipped", "hint")
    out = {k: job[k] for k in keys}
    out.update(percent=round(pct, 1), file_count=len(job["files"]))
    return out


# --------------------------------------------------------------------------- OS helpers
def open_in_explorer(path: str):
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


def pick_folder(initial: str) -> str | None:
    if IS_WIN:
        safe = initial.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$f.Description='Choose where TubeGrab saves downloads';$f.ShowNewFolderButton=$true;"
            f"$f.SelectedPath='{safe}';"
            "$o=New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            "if($f.ShowDialog($o) -eq 'OK'){$f.SelectedPath}"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                           text=True, encoding="utf-8", creationflags=0x08000000)
        return r.stdout.strip() or None
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(initialdir=initial)
        root.destroy()
        return chosen or None
    except Exception:  # noqa: BLE001
        return None


def update_ytdlp() -> dict:
    if FROZEN:
        where = f"https://github.com/{GITHUB_REPO}/releases" if GITHUB_REPO else "build-exe.bat"
        return {"ok": False, "message": f"This .exe has yt-dlp built in. Get the newest TubeGrab from {where}."}
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return {"ok": True, "message": "yt-dlp updated. Close TubeGrab and start it again to use the new version."}
    return {"ok": False, "message": (r.stderr or r.stdout)[-600:]}


# --------------------------------------------------------------------------- HTTP server
def load_ui() -> bytes:
    html = (RES_DIR / "ui.html").read_text("utf-8")
    return html.replace("__TOKEN__", TOKEN).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = APP_NAME

    def log_message(self, *args):
        pass

    def _send(self, code: int, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self, need_token=True) -> bool:
        # Block DNS-rebinding and drive-by requests from other websites.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        return not need_token or secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            if not self._allowed(need_token=False):
                return self._send(403, {"error": "forbidden"})
            return self._send(200, load_ui(), "text/html")
        if not self._allowed():
            return self._send(403, {"error": "forbidden"})
        if path == "/api/state":
            with LOCK:
                jobs = [public_job(j) for j in sorted(JOBS.values(), key=lambda j: j["created"])]
                return self._send(200, {"settings": SETTINGS, "jobs": jobs, "env": environment()})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            return self._send(403, {"error": "forbidden"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
            result = self.route(urlparse(self.path).path, data)
            return self._send(200, result if result is not None else {"ok": True})
        except KeyError as e:
            return self._send(404, {"error": f"Not found: {e}"})
        except Exception as e:  # noqa: BLE001
            msg = ANSI.sub("", str(e)).replace("ERROR: ", "")
            return self._send(400, {"error": msg[:600], "hint": hint_for([msg])})

    def route(self, path: str, data: dict):
        if path == "/api/settings":
            save_settings({**SETTINGS, **data})
            return {"settings": SETTINGS}
        if path == "/api/analyze":
            return analyze(str(data["url"]).strip())
        if path == "/api/jobs":
            job = new_job(data)
            with LOCK:
                JOBS[job["id"]] = job
            return public_job(job)
        m = re.fullmatch(r"/api/jobs/(\w+)/(cancel|retry|remove|open)", path)
        if m:
            with LOCK:
                job = JOBS[m.group(1)]
                action = m.group(2)
                if action == "cancel":
                    job["cancel"] = True
                    if job["status"] == "queued":
                        job["status"] = "cancelled"
                elif action == "retry" and job["status"] not in ACTIVE:
                    job["settings"] = dict(SETTINGS)
                    reset_job(job)
                elif action == "remove" and job["status"] not in ACTIVE:
                    del JOBS[job["id"]]
                elif action == "open":
                    target = job["files"][-1] if job["files"] else job["settings"]["download_dir"]
                    open_in_explorer(target if Path(target).exists() else job["settings"]["download_dir"])
            return None
        if path == "/api/jobs/clear":
            with LOCK:
                for jid in [j["id"] for j in JOBS.values() if j["status"] in ("done", "cancelled")]:
                    del JOBS[jid]
            return None
        if path == "/api/open-folder":
            folder = SETTINGS["download_dir"]
            Path(folder).mkdir(parents=True, exist_ok=True)
            open_in_explorer(folder)
            return None
        if path == "/api/browse":
            chosen = pick_folder(SETTINGS["download_dir"])
            if chosen:
                save_settings({**SETTINGS, "download_dir": chosen})
            return {"settings": SETTINGS, "chosen": bool(chosen)}
        if path == "/api/update":
            return update_ytdlp()
        if path == "/api/quit":
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        raise KeyError(path)


def main():
    load_settings()
    threading.Thread(target=dispatcher, daemon=True).start()
    threading.Thread(target=check_for_update, daemon=True).start()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"{APP_NAME} {APP_VERSION} (yt-dlp {yt_dlp.version.__version__})")
    print(f"Open {url} in your browser if it didn't open by itself.")
    print("Keep this window open while downloading. Close it (or press Ctrl+C) to quit.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.7, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("TubeGrab stopped.")


if __name__ == "__main__":
    main()
