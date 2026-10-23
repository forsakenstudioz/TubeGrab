# Changelog

## 1.0.0 - 2026-10-23

First release, replacing the old `bulk-youtube-download.bat` scripts.

- Browser-based UI: paste links, **Download** button (or Ctrl+Enter), **Paste** and **Import .txt**
- Video or audio (MP3 / M4A / Opus / FLAC / WAV), max-quality cap, MP4 or MKV
- Playlists: pick a range or tick individual items; "just this video" for `watch?v=…&list=…` links
- Live progress, speed, ETA, cancel / retry, parallel downloads
- Subtitles, thumbnails, metadata, chapters, SponsorBlock, speed limit, cookies from browser
- Skips things already downloaded (separately for video and audio)
- Checks for FFmpeg and Deno, friendly hints for common YouTube errors
- Tells users when a newer TubeGrab release is on GitHub
