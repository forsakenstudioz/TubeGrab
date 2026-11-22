# Changelog

## 1.2.0 - 2026-11-22

- **Sort downloads into folders:** import a CSV with a link column and a folder column
  (e.g. `1`, `2`, `Songs`). Each link's videos are saved in `Downloads\TubeGrab\<folder>`.
- Also works by typing or pasting `link, folder` per line (copying two columns from Excel works too)
- New **Folder** column in the list; click it or right-click a link to set or clear its folder
- Playlists with a folder go straight into that folder (no extra playlist subfolder)
- Download history is kept per folder, so the same video can be saved in two folders
- Example file: `docs/example-links.csv`

## 1.1.0 - 2026-10-23

TubeGrab is now a real desktop app instead of a page in your browser.

- New window: **1 · Paste your links → 2 · Format & save to → 3 · Choose what to download**, with a log and progress bars
- Checkbox list: tick exactly which playlist items you want; for `watch?v=…&list=…` links only that video is ticked
- Per-link Video / Audio (click the Format column or right-click a row)
- **Pause / Resume / Stop**, overall and per-file progress with speed and time left
- One click: paste links and press **Download checked**; they are read and downloaded straight away
- Paste button reads the clipboard directly (no browser permission needed)
- Light / Dark / System theme, settings window, "Forget download history"
- The .exe has no console window and has its own icon

## 1.0.0 - 2026-10-23

First release, replacing the old `bulk-youtube-download.bat` scripts.

- Video or audio (MP3 / M4A / Opus / FLAC / WAV), max-quality cap, MP4 or MKV
- Playlist range / item selection
- Subtitles, thumbnails, metadata, chapters, SponsorBlock, speed limit, cookies from browser
- Skips things already downloaded (separately for video and audio)
- Checks for FFmpeg and Deno, friendly hints for common YouTube errors
- Tells users when a newer TubeGrab release is on GitHub
