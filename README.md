# TubeGrab

A friendly desktop app for downloading YouTube videos, playlists and music, built on [yt-dlp](https://github.com/yt-dlp/yt-dlp).
Paste links, tick what you want, press **Download checked**. No more `links.txt` + batch files.

![TubeGrab screenshot](docs/screenshot.png)

## Download

Go to **[Releases](../../releases/latest)** and get:

- **`TubeGrab-portable-win64.zip`** (recommended): unzip anywhere and run `TubeGrab.exe`. FFmpeg and Deno are included, so there's nothing to install.
- **`TubeGrab.exe`**: just the app, if you already have FFmpeg and Deno (run `Install-Tools.bat` to get them).

Windows SmartScreen may warn about an unknown app the first time. Click **More info → Run anyway**.

## How to use

1. **Paste your links** into box 1: videos, playlists, channels or Shorts, one per line. You can also use **Paste**, or **Import .txt…** for an old `links.txt`.
2. **Format & save to**: pick *Video* (quality, MP4/MKV, subtitles) or *Audio only* (MP3, M4A, Opus, FLAC, WAV), and the folder.
3. **Choose what to download**: press **Load links** (or Ctrl+Enter) to see every video. Tick or untick items. Playlists can be expanded to pick single videos.
   - Click a link's **Format** cell (or right-click it) to download just that link as audio or video.
   - For a `watch?v=…&list=…` link only the video you opened is ticked; tick more if you want the rest.
4. Press **Download checked**. Use **Pause**, **Stop** and **Open folder** as needed.

In a hurry? Paste links and press **Download checked** straight away. They're read and downloaded in one go.

Videos are saved to `Downloads\TubeGrab`, audio to `Downloads\TubeGrab\Audio`.

### Sorting videos into folders (CSV)

Make a CSV (in Excel: *Save as → CSV UTF-8*) with a link column, a folder column and optionally a video number, then open it with **Import .txt / .csv…**:

| Folder no | Video No | Video Title | YouTube Link |
|---|---|---|---|
| 1 | 1 | … | https://youtu.be/… |
| 1 | 2 | … | https://youtu.be/… |
| 3 | 8 | … | https://youtu.be/waL-wFNi_mE |

That last row is saved as `Downloads\TubeGrab\3\08 - sollum porulum  2 [waL-wFNi_mE].mp4`:
the video number (zero-padded so files sort in order), the YouTube title, and the video ID.

- Columns are found by their header: anything with "folder" is the folder, "No" / "Number" is the video number. Other columns (title, notes) are ignored.
- Folder names can be numbers or words. Links without a folder go to the main folder; a playlist with a folder goes straight into it.
- A video listed twice in the same folder is downloaded once. The same video in two folders is saved in both.
- Audio downloads go in an `Audio` subfolder inside the folder.
- You can also type or paste `link, folder` lines into box 1, or copy the columns straight from Excel.

**See the structure before downloading:** the list groups links under **Folder 1, Folder 2…** (tick a heading to select the whole folder),
and **Preview structure…** shows every folder and the exact file names that will be created, with totals. It can also save them as a text file.
To move a link to another folder, click its **Folder** cell or right-click → **Set folder…**. See [`docs/example-links.csv`](docs/example-links.csv).

### Big lists (hundreds of videos)

- Single-video links are ready the moment they're imported, so press **Download checked** straight away.
  While it runs you can tick more and press **Add to queue**, or right-click → **Remove from queue**.
- YouTube limits how many requests one connection can make. TubeGrab pauses a few seconds between videos;
  for very big lists choose **Settings → Pause between videos → Safe**.
- If YouTube still says "rate-limited / try again later", TubeGrab doesn't fail the rest of the list: it waits
  (10 minutes, longer if it happens again) and then carries on with the same video. **Retry now** skips the wait.
- Stopped halfway? Import the same CSV again and press Download: finished videos are skipped.

## Settings

**Settings…** (top right) has the rest:

| Setting | What it does |
|---|---|
| Subtitle languages | e.g. `en.*,ta,hi`, optionally auto-generated subtitles too |
| Embed cover / metadata / chapters | Saved inside the file |
| Cut out sponsor segments | Removes sponsor / self-promo / "subscribe" bits via SponsorBlock |
| Playlists in their own folder, numbered files | `Playlist name/01 - Title.mp4` |
| Skip things I already downloaded | Remembers finished items (separately for video and audio); *Forget download history* resets it |
| Speed limit | e.g. `2M` so downloads don't hog the connection |
| Pause between videos | Normal (4-10 s) or Safe (10-20 s) so YouTube doesn't block big lists |
| Use cookies from | For age-restricted / members-only / "confirm you're not a bot" errors (Firefox works best) |
| Update yt-dlp | When running from source; YouTube changes often |

Errors show up in the log with a tip on how to fix them.

## Run from source

Needs Python 3.11+ with Tkinter (included in the python.org installer). Works on Windows, macOS and Linux.

```bat
Install-Tools.bat          :: once: FFmpeg + Deno (+ Python if missing) via winget
Start-TubeGrab.bat         :: installs yt-dlp on first run, then opens the window
```

Or manually: `pip install -U "yt-dlp[default]"`, then `python tubegrab.py`.
On Linux you may need your distro's Tk package (e.g. `sudo apt install python3-tk`).

Run the tests with `pip install pytest`, then `python -m pytest -q`.

## Making a new release (maintainers)

GitHub Actions builds everything on a Windows machine with the newest yt-dlp:

1. Update `CHANGELOG.md` and commit.
2. Tag and push:
   ```bat
   git tag v1.1.0
   git push origin v1.1.0
   ```
3. A few minutes later the release appears with `TubeGrab.exe` and the portable zip attached.
   The version number and repo name are stamped into the app automatically, so existing users get a "new version available" notice.

Because the .exe has yt-dlp built in, **make a new release whenever YouTube downloads start failing**. Even a release with no code changes picks up the latest yt-dlp.
To test a build without releasing, open **Actions → Build & release → Run workflow** and download the result from the run's *Artifacts*.

You can also build locally with `build-exe.bat`.

## Project layout

| File | What it is |
|---|---|
| `tubegrab.py` | The desktop window (Tkinter) |
| `tubegrab_core.py` | Everything that talks to yt-dlp: settings, reading links, downloading |
| `assets/tubegrab.ico` | App icon |
| `Start-TubeGrab.bat` / `Install-Tools.bat` / `build-exe.bat` | Windows helpers |
| `tests/` | Tests, including real local downloads |
| `.github/workflows/` | CI tests and the release build |

Settings and the download history live in `%APPDATA%\TubeGrab`.

## Credits

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) does all the downloading
- [FFmpeg](https://ffmpeg.org) (builds from [yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds)) and [Deno](https://deno.com) are bundled in the portable zip under their own licenses
- Started from the *Bulk YouTube Downloader* batch script by [EDM115](https://github.com/EDM115)

Only download content you have the right to download.
