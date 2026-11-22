# Changelog

## 1.2.0 - 2026-11-22

- **Sort downloads into folders:** import a CSV with a link column and a folder column
  (e.g. `1`, `2`, `Songs`). Each link's videos are saved in `Downloads\TubeGrab\<folder>`.
- Also works by typing or pasting `link, folder` per line (copying two columns from Excel works too)
- New **Folder** column in the list; click it or right-click a link to set or clear its folder
- Playlists with a folder go straight into that folder (no extra playlist subfolder)
- Download history is kept per folder, so the same video can be saved in two folders
- **Video number in file names:** a "Video No" column puts the number in front of each file
  (`08 - title [id].mp4`), zero-padded so files sort in course order
- **See the structure before downloading:** the list groups links under folder headings (tick a heading to
  select the whole folder), and **Preview structure…** shows every folder and exact file name, with totals
  and a "Save as text" option
- Folder headings show progress while downloading ("12 of 35 done")
- **No waiting before downloading:** single-video links are ready the moment you import them (no look-up first),
  so downloads start straight away. Playlists/channels are read in the background and join the queue by themselves.
- **Live queue:** while downloading, tick more and press **Add to queue**; right-click → **Remove from queue**
- **YouTube "rate-limited" protection:** a short pause between videos (Settings → Pause between videos), and when
  YouTube still says "slow down", TubeGrab waits (10 min, longer if it repeats), then retries the same video by
  itself - those videos are no longer marked as failed. **Retry now** skips the wait.
- Big lists load much faster (1,500+ links in under a second)
- CSV separator is detected once per file, so a `;` inside a title can't break a row
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
