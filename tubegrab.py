#!/usr/bin/env python3
"""
TubeGrab - a desktop app for downloading YouTube videos, playlists and music (built on yt-dlp).

Run it with:   python tubegrab.py
"""
from __future__ import annotations

import collections
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# A windowed .exe has no console; give libraries somewhere harmless to print.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

try:
    import tubegrab_core as core
except ImportError as _e:  # yt-dlp missing
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror("TubeGrab", f"yt-dlp is not installed ({_e}).\n\n"
                         "Install it with:\n    python -m pip install -U \"yt-dlp[default]\"\n\n"
                         "or just double-click Start-TubeGrab.bat.")
    sys.exit(1)

APP_NAME = core.APP_NAME
THEMES = ["System", "Light", "Dark"]

QUALITIES = [("best", "Best"), ("2160", "4K (2160p)"), ("1440", "1440p"), ("1080", "1080p"),
             ("720", "720p"), ("480", "480p"), ("360", "360p")]
CONTAINERS = [("mp4", "MP4"), ("mkv", "MKV")]
AUDIO_FORMATS = [("mp3", "MP3"), ("m4a", "M4A (AAC)"), ("opus", "Opus"), ("flac", "FLAC"), ("wav", "WAV")]
BITRATES = [("0", "Best"), ("320", "320 kbps"), ("256", "256 kbps"), ("192", "192 kbps"), ("128", "128 kbps")]
PACINGS = [("off", "Off"), ("normal", "Normal (4-10 s)"), ("safe", "Safe (10-20 s)")]
COOKIE_BROWSERS = [("", "Off"), ("firefox", "Firefox"), ("chrome", "Chrome"), ("edge", "Edge"),
                   ("brave", "Brave"), ("opera", "Opera"), ("vivaldi", "Vivaldi"), ("safari", "Safari")]

PALETTES = {
    "Light": dict(bg="#f4f5f7", panel="#ffffff", fg="#1d1f23", muted="#5d6470", border="#d3d8de",
                  accent="#d93b30", accent_hover="#bf3127", accent_fg="#ffffff", select="#fbe3e1",
                  entry="#ffffff", trough="#e4e7eb", ok="#18794e", warn="#9a6200", err="#c9252d",
                  log_bg="#fbfbfc"),
    "Dark": dict(bg="#1c1d21", panel="#26282d", fg="#e7e8ea", muted="#a2a7b0", border="#3a3d44",
                 accent="#ff6b5e", accent_hover="#ff8478", accent_fg="#111111", select="#4a2c29",
                 entry="#202227", trough="#33363c", ok="#46c08a", warn="#e0a53a", err="#ff6b6b",
                 log_bg="#18191c"),
}

FINAL = ("✓ Done", "Already have", "✗ Failed", "Stopped", "Not downloaded")


# ----------------------------------------------------------------------------------- helpers
def system_theme() -> str:
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return "Light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "Dark"
        import subprocess
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2).stdout
            return "Dark" if "Dark" in out else "Light"
        for cmd in (["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"]):
            try:
                if "dark" in subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.lower():
                    return "Dark"
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return "Light"


def ui_font() -> tuple:
    if sys.platform == "win32":
        return ("Segoe UI", 10)
    try:
        fam = tkfont.nametofont("TkDefaultFont").actual("family")
    except Exception:  # noqa: BLE001
        fam = "Helvetica"
    return (fam, 13 if sys.platform == "darwin" else 10)


def mono_font() -> tuple:
    if sys.platform == "win32":
        return ("Consolas", 9)
    if sys.platform == "darwin":
        return ("Menlo", 11)
    return ("DejaVu Sans Mono", 9) if "DejaVu Sans Mono" in tkfont.families() else ("TkFixedFont",)


def check_image(master, state: str, pal: dict, size: int = 16, img: tk.PhotoImage | None = None) -> tk.PhotoImage:
    """Draw a checkbox picture: 'on', 'off', 'partial' or 'none' (blank). Redraws `img` if given."""
    if img is None:
        img = tk.PhotoImage(master=master, width=size, height=size)
    else:
        img.blank()
    if state == "none":
        return img
    edge = pal["accent"] if state != "off" else pal["muted"]
    img.put(edge, to=(3, 1, 13, 15))
    img.put(edge, to=(1, 3, 15, 13))
    img.put(edge, to=(2, 2, 14, 14))
    if state == "off":
        fill = pal["entry"]
        img.put(fill, to=(3, 3, 13, 13))
        img.put(fill, to=(4, 2, 12, 14))
        img.put(fill, to=(2, 4, 14, 12))
        return img
    mark = pal["accent_fg"] if pal["accent_fg"] != "#111111" else "#ffffff"
    if state == "partial":
        img.put(mark, to=(4, 7, 12, 9))
        return img
    for i in range(4):          # short stroke down-right
        img.put(mark, to=(4 + i, 7 + i, 5 + i, 9 + i))
    for i in range(6):          # long stroke up-right
        img.put(mark, to=(7 + i, 10 - i, 8 + i, 12 - i))
    return img


def app_icon(master, color: str) -> tk.PhotoImage:
    """32x32 window icon: rounded red square with a white download arrow."""
    img = tk.PhotoImage(master=master, width=32, height=32)
    img.put(color, to=(2, 0, 30, 32))
    img.put(color, to=(0, 2, 32, 30))
    img.put(color, to=(1, 1, 31, 31))
    w = "#ffffff"
    img.put(w, to=(14, 6, 18, 20))                      # shaft
    for i in range(6):                                  # arrow head
        img.put(w, to=(9 + i, 14 + i, 23 - i, 16 + i))
    img.put(w, to=(8, 24, 24, 27))                      # base line
    return img


# ----------------------------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  v{core.APP_VERSION}")
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96)
        w = min(int(1060 * self.scale), self.winfo_screenwidth() - 40)
        h = min(int(880 * self.scale), self.winfo_screenheight() - 80)   # fits 1366x768 laptops too
        self.geometry(f"{w}x{h}")
        self.compact = self.winfo_screenheight() < 900 * self.scale     # small laptop screens
        self.minsize(min(int(860 * self.scale), w), min(int(600 * self.scale), h))
        self.cfg = core.load_settings()
        self.q: queue.Queue = queue.Queue()
        self.pal = PALETTES["Light"]
        self.imgs: dict = {}

        # tree model
        self.links: dict = {}        # link iid -> {"url", "info", "mode", "touched", "state"}
        self.child_of: dict = {}     # child iid -> (link iid, entry)
        self.checked: set = set()    # leaf iids (video link rows and playlist item rows)
        self.folder_nodes: dict = {} # CSV folder name -> its heading row in the list
        self._folder_iids: set = set()
        self._summary_due = False
        # Playlists/channels must be read before you can pick from them. One reader with a short gap between
        # links keeps YouTube happy; single videos don't need reading at all.
        self.analyse_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._analyse_loop, daemon=True).start()
        self.dl_q: collections.deque = collections.deque()   # plan numbers waiting to download (the live queue)
        self.dl_lock = threading.Lock()
        self.worker_running = False
        self.in_queue: set = set()                  # rows queued / downloading / finished this session
        self.skip_wait = threading.Event()          # "Retry now" during a YouTube cool-down
        self.cooldown_until = 0.0

        # download state
        self.downloading = False
        self.cancel = threading.Event()
        self.pause = threading.Event()
        self.plans: list = []
        self.done_rows: set = set()
        self.total_items = 0
        self.cur_row = None
        self.cur_frac = 0.0
        self.counts = {"ok": 0, "skip": 0, "fail": 0, "stop": 0}
        self.update_info = None

        self._build()
        self.apply_theme(self.cfg["theme"])
        self._sync_mode_widgets()
        self.after(100, self._poll)
        self.after(250, self._fit_split)
        if self.compact and sys.platform == "win32":
            try:
                self.state("zoomed")
            except tk.TclError:
                pass
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=lambda: self.q.put(("update", core.check_for_update())), daemon=True).start()
        self._startup_checks()

    # =========================================================================== UI layout
    def _build(self):
        pad = {"padx": 6, "pady": 3}
        main = ttk.Frame(self, padding=(12, 8, 12, 10))
        main.pack(fill="both", expand=True)

        # --- header ---
        head = ttk.Frame(main)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text=APP_NAME, style="Title.TLabel").pack(side="left")
        self.tools_lbl = ttk.Label(head, text="", style="Muted.TLabel")
        self.tools_lbl.pack(side="left", padx=(12, 0), pady=(6, 0))
        self.theme_var = tk.StringVar(value=self.cfg["theme"])
        cb = ttk.Combobox(head, textvariable=self.theme_var, values=THEMES, width=8, state="readonly")
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_theme(self.theme_var.get()))
        ttk.Label(head, text="Theme:", style="Muted.TLabel").pack(side="right", padx=(0, 4))
        self.btn_settings = ttk.Button(head, text="Settings…", command=self._settings_dialog)
        self.btn_settings.pack(side="right", padx=(0, 14))
        self.update_lbl = ttk.Label(head, text="", style="Link.TLabel", cursor="hand2")
        self.update_lbl.pack(side="right", padx=(0, 14))
        self.update_lbl.bind("<Button-1>", lambda e: self.update_info and webbrowser.open(self.update_info["url"]))

        # --- 1. links ---
        lnk = ttk.LabelFrame(main, text=" 1 · Paste your links ", padding=8)
        lnk.pack(fill="x")
        tw = ttk.Frame(lnk)
        tw.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.links_txt = tk.Text(tw, height=2 if self.compact else 3, wrap="none", relief="flat", borderwidth=0,
                                 highlightthickness=1, undo=True, font=ui_font())
        self.links_txt.pack(fill="both", expand=True)
        self.links_txt.bind("<Control-Return>", lambda e: (self._load_links(), "break")[1])
        self.links_txt.bind("<Command-Return>", lambda e: (self._load_links(), "break")[1])
        bx = ttk.Frame(lnk)                    # stacked buttons; side by side on small screens
        bx.grid(row=0, column=1, sticky="n")
        self.btn_load = ttk.Button(bx, text="Load links", style="Accent.TButton", command=self._load_links)
        self.btn_paste = ttk.Button(bx, text="Paste", command=self._paste)
        self.btn_import = ttk.Button(bx, text="Import .txt / .csv…", command=self._import_txt)
        for b in (self.btn_load, self.btn_paste, self.btn_import):
            if self.compact:
                b.pack(side="left", padx=(0, 6))
            else:
                b.pack(side="top", fill="x", padx=6, pady=3)
        if not self.compact:
            ttk.Label(lnk, text="Videos, playlists, channels or Shorts - one per line. "
                                "To sort into folders, write  link, 1  or import a CSV.",
                      style="Muted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        lnk.columnconfigure(0, weight=1)

        # --- 2. format & folder ---
        fmt = ttk.LabelFrame(main, text=" 2 · Format & save to ", padding=8)
        fmt.pack(fill="x", pady=(8, 0))
        ttk.Label(fmt, text="Save to:").grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar(value=self.cfg["download_dir"])
        self.dir_entry = ttk.Entry(fmt, textvariable=self.dir_var)
        self.dir_entry.grid(row=0, column=1, sticky="we", **pad)
        self.dir_entry.bind("<FocusOut>", lambda e: self._save_cfg())
        self.btn_browse = ttk.Button(fmt, text="Browse…", command=self._browse)
        self.btn_browse.grid(row=0, column=2, sticky="we", **pad)

        opt = ttk.Frame(fmt)
        opt.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(opt, text="Download as:").pack(side="left")
        self.mode_var = tk.StringVar(value=self.cfg["mode"])
        for val, label in (("video", "Video"), ("audio", "Audio only")):
            ttk.Radiobutton(opt, text=label, value=val, variable=self.mode_var,
                            command=self._mode_changed).pack(side="left", padx=(6, 2))
        ttk.Separator(opt, orient="vertical").pack(side="left", fill="y", padx=12)

        self.vid_box = ttk.Frame(opt)
        self.vid_box.pack(side="left")
        ttk.Label(self.vid_box, text="Quality:").pack(side="left")
        self.quality_var = self._choice_var(QUALITIES, self.cfg["video_quality"])
        ttk.Combobox(self.vid_box, textvariable=self.quality_var, values=[l for _, l in QUALITIES],
                     width=10, state="readonly").pack(side="left", padx=(4, 12))
        ttk.Label(self.vid_box, text="File:").pack(side="left")
        self.cont_var = self._choice_var(CONTAINERS, self.cfg["video_container"])
        ttk.Combobox(self.vid_box, textvariable=self.cont_var, values=[l for _, l in CONTAINERS],
                     width=5, state="readonly").pack(side="left", padx=(4, 12))
        self.subs_var = tk.BooleanVar(value=self.cfg["subtitles"])
        ttk.Checkbutton(self.vid_box, text="Subtitles", variable=self.subs_var,
                        command=self._save_cfg).pack(side="left")

        self.aud_box = ttk.Frame(opt)
        ttk.Label(self.aud_box, text="Format:").pack(side="left")
        self.afmt_var = self._choice_var(AUDIO_FORMATS, self.cfg["audio_format"])
        ttk.Combobox(self.aud_box, textvariable=self.afmt_var, values=[l for _, l in AUDIO_FORMATS],
                     width=10, state="readonly").pack(side="left", padx=(4, 12))
        ttk.Label(self.aud_box, text="Quality:").pack(side="left")
        self.abr_var = self._choice_var(BITRATES, self.cfg["audio_quality"])
        ttk.Combobox(self.aud_box, textvariable=self.abr_var, values=[l for _, l in BITRATES],
                     width=9, state="readonly").pack(side="left", padx=(4, 0))
        fmt.columnconfigure(1, weight=1)
        for v in (self.quality_var, self.cont_var, self.afmt_var, self.abr_var):
            v.trace_add("write", lambda *a: self.after_idle(self._options_changed))

        # --- progress ---
        pf = ttk.Frame(main)
        pf.pack(side="bottom", fill="x", pady=(8, 0))
        self.overall_lbl = ttk.Label(pf, text="Ready.")
        self.overall_lbl.pack(anchor="w")
        self.overall_bar = ttk.Progressbar(pf, mode="determinate", maximum=1000)
        self.overall_bar.pack(fill="x", pady=(2, 0))
        self.file_lbl = ttk.Label(pf, text="", style="Muted.TLabel")
        self.file_lbl.pack(anchor="w", pady=(4, 0))
        self.file_bar = ttk.Progressbar(pf, mode="determinate", maximum=1000, style="Thin.Horizontal.TProgressbar")
        self.file_bar.pack(fill="x", pady=(2, 0))

        # --- action bar ---
        bf = ttk.Frame(main)
        bf.pack(side="bottom", fill="x", pady=(8, 0))
        self.btn_go = ttk.Button(bf, text="Download checked", style="Accent.TButton", command=self._download_clicked)
        self.btn_go.pack(side="left")
        self.btn_pause = ttk.Button(bf, text="Pause", command=self._toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(bf, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left")
        ttk.Button(bf, text="Open folder", command=self._open_folder).pack(side="right")

        # --- 3. tree + log in a resizable split ---
        split = self.split = ttk.PanedWindow(main, orient="vertical")
        split.pack(fill="both", expand=True, pady=(8, 0))

        tf = ttk.LabelFrame(split, text=" 3 · Choose what to download ", padding=6)
        bar = ttk.Frame(tf)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="Check all", command=lambda: self._check_all(True)).pack(side="left")
        ttk.Button(bar, text="Uncheck all", command=lambda: self._check_all(False)).pack(side="left", padx=4)
        ttk.Button(bar, text="Expand all", command=lambda: self._expand_all(True)).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Collapse all", command=lambda: self._expand_all(False)).pack(side="left", padx=4)
        self.btn_clear = ttk.Button(bar, text="Clear list", command=self._clear_list)
        self.btn_clear.pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Preview structure…", command=self._preview_structure).pack(side="left", padx=(12, 0))
        self.summary_lbl = ttk.Label(bar, text="Paste links above to begin.", style="Muted.TLabel")
        self.summary_lbl.pack(side="right")

        tree_wrap = ttk.Frame(tf)
        tree_wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_wrap, columns=("format", "folder", "length", "status"),
                                 selectmode="browse")
        self.tree.heading("#0", text="Video / playlist   (click to check / uncheck)")
        self.tree.heading("format", text="Format")
        self.tree.heading("folder", text="Folder")
        self.tree.heading("length", text="Length")
        self.tree.heading("status", text="Status")
        s = self.scale
        self.tree.column("#0", width=int(450 * s), stretch=True)
        self.tree.column("folder", width=int(80 * s), anchor="center", stretch=False)
        self.tree.column("format", width=int(110 * s), anchor="center", stretch=False)
        self.tree.column("length", width=int(80 * s), anchor="e", stretch=False)
        self.tree.column("status", width=int(170 * s), anchor="center", stretch=False)
        ysb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_tree_space)
        self.tree.bind("<Delete>", lambda e: self._remove_selected())
        self.tree.bind("<Button-3>", self._on_tree_menu)
        self.tree.bind("<Button-2>" if sys.platform == "darwin" else "<Control-Button-1>", self._on_tree_menu)
        split.add(tf, weight=4)

        self.menu = tk.Menu(self, tearoff=False)

        lf = ttk.LabelFrame(split, text=" Log ", padding=4)
        lbar = ttk.Frame(lf)
        if not self.compact:                   # small screens: Clear / Save are on the log's right-click menu
            lbar.pack(fill="x")
        ttk.Button(lbar, text="Save log…", command=self._save_log).pack(side="right")
        ttk.Button(lbar, text="Clear", command=self._clear_log).pack(side="right", padx=4)
        ttk.Label(lbar, text="Errors come with a tip on how to fix them.", style="Muted.TLabel").pack(side="left")
        lw = ttk.Frame(lf)
        lw.pack(fill="both", expand=True, pady=(4, 0))
        self.log_txt = tk.Text(lw, height=3 if self.compact else 5, wrap="word", state="disabled", relief="flat",
                               borderwidth=0, highlightthickness=1, font=mono_font())
        lsb = ttk.Scrollbar(lw, orient="vertical", command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=lsb.set)
        self.log_txt.pack(side="left", fill="both", expand=True)
        self.log_menu = tk.Menu(self, tearoff=False)
        self.log_menu.add_command(label="Copy", command=lambda: self.log_txt.event_generate("<<Copy>>"))
        self.log_menu.add_command(label="Save log…", command=self._save_log)
        self.log_menu.add_command(label="Clear log", command=self._clear_log)
        for seq in ("<Button-3>", "<Button-2>" if sys.platform == "darwin" else "<Control-Button-1>"):
            self.log_txt.bind(seq, lambda e: self.log_menu.tk_popup(e.x_root, e.y_root))
        lsb.pack(side="right", fill="y")
        split.add(lf, weight=1)

        self.option_widgets = [w for w in self._all_children(lnk) + self._all_children(fmt)
                               if isinstance(w, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton,
                                                 ttk.Radiobutton))] + [self.btn_settings, self.btn_clear]

    def _fit_split(self):
        """Give the video list most of the free space; the log keeps about a quarter."""
        self.update_idletasks()
        total = self.split.winfo_height()
        if total > 50:
            log_h = max(int(90 * self.scale), int(total * 0.27))
            self.split.sashpos(0, max(int(110 * self.scale), total - log_h))

    def _choice_var(self, pairs, value) -> tk.StringVar:
        label = dict(pairs).get(value, pairs[0][1])
        var = tk.StringVar(value=label)
        var._pairs = pairs  # type: ignore[attr-defined]
        return var

    @staticmethod
    def _choice(var) -> str:
        return {l: v for v, l in var._pairs}.get(var.get(), var._pairs[0][0])

    def _all_children(self, w):
        out = []
        for c in w.winfo_children():
            out.append(c)
            out.extend(self._all_children(c))
        return out

    # =========================================================================== theme
    def _set_theme(self, choice: str):
        self.theme_var.set(choice)
        self.cfg["theme"] = choice
        core.save_settings(self.cfg)
        self.apply_theme(choice)

    def apply_theme(self, choice: str):
        mode = system_theme() if choice == "System" else choice
        p = self.pal = PALETTES.get(mode, PALETTES["Light"])
        st = ttk.Style(self)
        st.theme_use("clam")
        base_font = ui_font()
        st.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["entry"],
                     bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                     troughcolor=p["trough"], focuscolor=p["accent"], selectbackground=p["accent"],
                     selectforeground=p["accent_fg"], insertcolor=p["fg"], font=base_font)
        st.configure("TFrame", background=p["bg"])
        st.configure("TLabel", background=p["bg"], foreground=p["fg"])
        st.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
        st.configure("Warn.TLabel", background=p["bg"], foreground=p["warn"])
        st.configure("Link.TLabel", background=p["bg"], foreground=p["ok"],
                     font=(base_font[0], base_font[1], "bold underline"))
        st.configure("Title.TLabel", background=p["bg"], foreground=p["fg"],
                     font=(base_font[0], base_font[1] + 5, "bold"))
        st.configure("TLabelframe", background=p["bg"], bordercolor=p["border"], relief="solid")
        st.configure("TLabelframe.Label", background=p["bg"], foreground=p["muted"],
                     font=(base_font[0], base_font[1], "bold"))
        st.configure("TButton", background=p["panel"], foreground=p["fg"], bordercolor=p["border"],
                     padding=(10, 4), relief="flat")
        st.map("TButton", background=[("disabled", p["bg"]), ("pressed", p["select"]), ("active", p["select"])],
               foreground=[("disabled", p["muted"])])
        st.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                     bordercolor=p["accent"], font=(base_font[0], base_font[1], "bold"))
        st.map("Accent.TButton", background=[("disabled", p["trough"]), ("pressed", p["accent_hover"]),
                                             ("active", p["accent_hover"])],
               foreground=[("disabled", p["muted"])])
        for w in ("TCheckbutton", "TRadiobutton"):
            st.configure(w, background=p["bg"], foreground=p["fg"],
                         indicatorbackground=p["entry"], indicatorforeground=p["accent"])
            st.map(w, background=[("active", p["bg"])], foreground=[("disabled", p["muted"])],
                   indicatorbackground=[("selected", p["entry"]), ("active", p["entry"])])
        st.configure("TEntry", fieldbackground=p["entry"], foreground=p["fg"], insertcolor=p["fg"],
                     bordercolor=p["border"], padding=4)
        st.map("TEntry", bordercolor=[("focus", p["accent"])], fieldbackground=[("disabled", p["bg"])],
               foreground=[("disabled", p["muted"])])
        st.configure("TSpinbox", fieldbackground=p["entry"], background=p["panel"], foreground=p["fg"],
                     arrowcolor=p["fg"], bordercolor=p["border"], insertcolor=p["fg"], padding=3)
        st.map("TSpinbox", bordercolor=[("focus", p["accent"])])
        st.configure("TCombobox", fieldbackground=p["entry"], background=p["panel"], foreground=p["fg"],
                     arrowcolor=p["fg"], bordercolor=p["border"], padding=3)
        st.map("TCombobox", fieldbackground=[("readonly", p["entry"]), ("disabled", p["bg"])],
               foreground=[("readonly", p["fg"]), ("disabled", p["muted"])],
               selectbackground=[("readonly", p["entry"])], selectforeground=[("readonly", p["fg"])])
        st.configure("Treeview", background=p["panel"], fieldbackground=p["panel"], foreground=p["fg"],
                     bordercolor=p["border"], rowheight=int((23 if self.compact else 26) * self.scale))
        st.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["fg"])])
        st.configure("Treeview.Heading", background=p["bg"], foreground=p["muted"], relief="flat",
                     bordercolor=p["border"], font=(base_font[0], base_font[1] - 1, "bold"))
        st.map("Treeview.Heading", background=[("active", p["select"])])
        st.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["trough"],
                     bordercolor=p["trough"], lightcolor=p["accent"], darkcolor=p["accent"],
                     thickness=int(12 * self.scale))
        st.configure("Thin.Horizontal.TProgressbar", background=p["accent"], troughcolor=p["trough"],
                     bordercolor=p["trough"], lightcolor=p["accent"], darkcolor=p["accent"],
                     thickness=int(6 * self.scale))
        st.configure("Vertical.TScrollbar", background=p["panel"], troughcolor=p["bg"],
                     bordercolor=p["bg"], arrowcolor=p["muted"])
        st.configure("TPanedwindow", background=p["bg"])
        st.configure("TSeparator", background=p["border"])
        self.configure(bg=p["bg"])
        self.option_add("*TCombobox*Listbox.background", p["entry"])
        self.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])
        for t in (self.links_txt, self.log_txt):
            t.configure(bg=p["log_bg"] if t is self.log_txt else p["entry"], fg=p["fg"], insertbackground=p["fg"],
                        highlightbackground=p["border"], highlightcolor=p["accent"],
                        selectbackground=p["accent"], selectforeground=p["accent_fg"])
        self.log_txt.tag_configure("muted", foreground=p["muted"])
        self.log_txt.tag_configure("ok", foreground=p["ok"])
        self.log_txt.tag_configure("warn", foreground=p["warn"])
        self.log_txt.tag_configure("err", foreground=p["err"])
        for m in (self.menu, self.log_menu):
            m.configure(bg=p["panel"], fg=p["fg"], activebackground=p["select"], activeforeground=p["fg"])
        self.tree.tag_configure("link", font=(base_font[0], base_font[1], "bold"))
        self.tree.tag_configure("folder", font=(base_font[0], base_font[1], "bold"), foreground=p["accent"])
        self.tree.tag_configure("failed", foreground=p["err"])
        self.tree.tag_configure("done", foreground=p["ok"])
        self.tree.tag_configure("muted", foreground=p["muted"])

        size = 16
        self.imgs = {k: check_image(self, k, p, size) for k in ("on", "off", "partial", "none")}
        if self.scale >= 1.75:
            self.imgs = {k: v.zoom(2) for k, v in self.imgs.items()}
        self._style_checkbuttons(st, p)
        self._icon = app_icon(self, PALETTES["Light"]["accent"])
        self.iconphoto(True, self._icon)
        ico = core.RES_DIR / "assets" / "tubegrab.ico"
        if core.IS_WIN and ico.is_file():
            try:
                self.iconbitmap(default=str(ico))   # sharper in the Windows taskbar
            except tk.TclError:
                pass
        for iid in self.links:
            self._refresh_check(iid)

    def _style_checkbuttons(self, st: ttk.Style, p: dict):
        """Give ttk checkbuttons the same red tick boxes as the list (clam's default is a plain X)."""
        if not hasattr(self, "_cb_imgs"):
            self._cb_imgs = {k: tk.PhotoImage(master=self, width=16, height=16) for k in ("on", "off", "don", "doff")}
        dis = dict(p, accent=p["muted"])
        for key, state, pal in (("on", "on", p), ("off", "off", p), ("don", "on", dis), ("doff", "off", dis)):
            check_image(self, state, pal, img=self._cb_imgs[key])
        if not getattr(self, "_cb_element", False):
            i = self._cb_imgs
            st.element_create("tg.Checkbutton.indicator", "image", i["off"],
                              ("disabled", "selected", i["don"]), ("disabled", i["doff"]), ("selected", i["on"]),
                              border=0, sticky="", padding=(0, 0, 5, 0))
            st.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("tg.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"})]})]})])
            self._cb_element = True

    # =========================================================================== settings
    def _options_changed(self):
        self._save_cfg()
        self._refresh_formats()

    def _save_cfg(self):
        self.cfg.update(
            download_dir=self.dir_var.get().strip() or self.cfg["download_dir"],
            mode=self.mode_var.get(), video_quality=self._choice(self.quality_var),
            video_container=self._choice(self.cont_var), subtitles=self.subs_var.get(),
            audio_format=self._choice(self.afmt_var), audio_quality=self._choice(self.abr_var),
            theme=self.theme_var.get())
        self.cfg = core.clean_settings(self.cfg)
        core.save_settings(self.cfg)

    def _mode_changed(self):
        mode = self.mode_var.get()
        for L in self.links.values():
            if not L["touched"]:
                L["mode"] = mode
        self._sync_mode_widgets()
        self._save_cfg()
        self._refresh_formats()

    def _sync_mode_widgets(self):
        if self.mode_var.get() == "audio":
            self.vid_box.pack_forget()
            self.aud_box.pack(side="left")
        else:
            self.aud_box.pack_forget()
            self.vid_box.pack(side="left")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or str(Path.home()),
                                    title="Choose where TubeGrab saves downloads", parent=self)
        if d:
            self.dir_var.set(str(Path(d)))
            self._save_cfg()

    def _settings_dialog(self):
        p = self.pal
        win = tk.Toplevel(self)
        win.title("Settings")
        win.transient(self)
        win.configure(bg=p["bg"])
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        c = self.cfg
        v = {k: tk.BooleanVar(value=c[k]) for k in ("auto_subtitles", "embed_thumbnail", "embed_metadata",
                                                     "embed_chapters", "sponsorblock", "skip_downloaded",
                                                     "playlist_folder", "number_playlist_items")}
        langs = tk.StringVar(value=c["sub_langs"])
        rate = tk.StringVar(value=c["rate_limit"])
        frags = tk.StringVar(value=str(c["concurrent_fragments"]))
        cookies = self._choice_var(COOKIE_BROWSERS, c["cookies_browser"])
        pacing = self._choice_var(PACINGS, c["pacing"])

        row = 0

        def head(text):
            nonlocal row
            ttk.Label(frm, text=text, style="Muted.TLabel", font=(ui_font()[0], ui_font()[1], "bold")
                      ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10 if row else 0, 2))
            row += 1

        def check(key, text):
            nonlocal row
            ttk.Checkbutton(frm, text=text, variable=v[key]).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
            row += 1

        def field(text, widget, note=""):
            nonlocal row
            ttk.Label(frm, text=text).grid(row=row, column=0, sticky="w", pady=2)
            widget.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=2)
            row += 1
            if note:
                ttk.Label(frm, text=note, style="Muted.TLabel").grid(row=row, column=0, columnspan=2, sticky="w")
                row += 1

        head("Subtitles (video)")
        field("Languages:", ttk.Entry(frm, textvariable=langs, width=22), "Comma separated, e.g.  en.*,ta,hi")
        check("auto_subtitles", "Also use auto-generated subtitles")
        head("Extras")
        check("embed_thumbnail", "Embed cover / thumbnail")
        check("embed_metadata", "Embed title, artist and description")
        check("embed_chapters", "Embed chapters")
        check("sponsorblock", "Cut out sponsor segments (SponsorBlock)")
        head("Organising")
        check("playlist_folder", "Put playlists in their own folder")
        check("number_playlist_items", "Number playlist files (01 - ...)")
        check("skip_downloaded", "Skip things I already downloaded")
        head("Network")
        field("Speed limit:", ttk.Entry(frm, textvariable=rate, width=10), "e.g.  2M  or  500K  (empty = unlimited)")
        field("Parallel fragments:", ttk.Spinbox(frm, from_=1, to=16, textvariable=frags, width=6))
        field("Pause between videos:", ttk.Combobox(frm, textvariable=pacing, values=[l for _, l in PACINGS],
                                                    width=16, state="readonly"),
              "Stops YouTube from blocking you on big lists. 'Safe' is best for hundreds of videos.")
        field("Use cookies from:", ttk.Combobox(frm, textvariable=cookies, values=[l for _, l in COOKIE_BROWSERS],
                                                width=10, state="readonly"),
              "For age-restricted / members-only / \"confirm you're not a bot\". Firefox is most reliable.")
        head("Maintenance")
        mb = ttk.Frame(frm)
        mb.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Button(mb, text="Update yt-dlp", command=lambda: self._update_ytdlp(win)).pack(side="left")
        ttk.Button(mb, text="Forget download history", command=lambda: self._forget_history(win)
                   ).pack(side="left", padx=6)
        ttk.Label(frm, text=f"TubeGrab {core.APP_VERSION}  ·  yt-dlp {core.ytdlp_version()}"
                  + (f"  ·  github.com/{core.GITHUB_REPO}" if core.GITHUB_REPO else ""),
                  style="Muted.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1

        def ok():
            new = {k: var.get() for k, var in v.items()}
            new.update(sub_langs=langs.get(), rate_limit=rate.get(), concurrent_fragments=frags.get() or 4,
                       cookies_browser=self._choice(cookies), pacing=self._choice(pacing))
            self.cfg = core.clean_settings(new, self.cfg)
            core.save_settings(self.cfg)
            win.destroy()

        bb = ttk.Frame(frm)
        bb.grid(row=row, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(bb, text="Save", style="Accent.TButton", command=ok).pack(side="right", padx=6)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()   # centre over the main window
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_reqwidth()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_reqheight()) // 3)
        win.geometry(f"+{x}+{y}")
        win.grab_set()

    def _update_ytdlp(self, parent):
        self.config(cursor="watch")
        parent.config(cursor="watch")

        def job():
            ok, msg = core.update_ytdlp()
            self.q.put(("msg", ok, msg))
        threading.Thread(target=job, daemon=True).start()

    def _forget_history(self, parent):
        if messagebox.askyesno(APP_NAME, "Forget which videos you already downloaded?\n\n"
                               "They will be downloaded again next time.", parent=parent):
            for f in core.history_files():
                try:
                    f.unlink()
                except OSError:
                    pass
            self._log("Download history cleared.", "muted")

    # =========================================================================== links
    def _paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        if not core.extract_urls(text):
            messagebox.showinfo(APP_NAME, "The clipboard doesn't contain a link.\n\nCopy a YouTube link first.")
            return
        cur = self.links_txt.get("1.0", "end").strip()
        self.links_txt.insert("end", ("\n" if cur else "") + text.strip() + "\n")
        self.links_txt.see("end")
        self.links_txt.focus_set()

    def _import_txt(self):
        f = filedialog.askopenfilename(title="Import links", parent=self,
                                       filetypes=[("Text files", "*.txt *.csv *.json"), ("All files", "*.*")])
        if f:
            try:
                text = core.read_text_file(f)
            except OSError as e:
                messagebox.showerror(APP_NAME, f"Couldn't read the file:\n{e}")
                return
            self.links_txt.insert("end", "\n" + text)
            self._load_links()

    def _load_links(self, auto: bool = False) -> int:
        rows = core.parse_link_rows(self.links_txt.get("1.0", "end"))
        if not rows:
            if not auto:
                messagebox.showinfo(APP_NAME, "Paste one or more YouTube links in the box first.")
            return 0
        known = {(L["url"], L["folder"]) for L in self.links.values()}
        added = ready = 0
        new_singles = []
        for r in rows:
            url, folder = r["url"], r["folder"]
            if (url, folder) in known:
                continue
            known.add((url, folder))
            L = {"url": url, "info": None, "mode": self.mode_var.get(), "touched": False,
                 "state": "loading", "folder": folder, "number": r["number"]}
            parent = self._folder_node(folder) if folder else ""
            vid = core.single_video_id(url)
            if vid:
                # One video: nothing to choose, so it's ready now. No look-up (that's what made YouTube block
                # big lists) - its YouTube title appears when it downloads.
                L.update(state="ready", info={"kind": "video", "url": url, "id": vid, "title": r["title"] or vid,
                                              "duration": None, "count": 1, "provisional": True})
                iid = self.tree.insert(parent, "end", text="", values=("", folder or "", "", ""),
                                       tags=("link",), image=self.imgs["on"])
                self.links[iid] = L
                self.checked.add(iid)
                new_singles.append(iid)
                ready += 1
            else:
                iid = self.tree.insert(parent, "end", text="  Reading link…", values=("", folder or "", "", "Loading…"),
                                       tags=("link", "muted"), image=self.imgs["on"])
                self.links[iid] = L
                self.checked.add(iid)          # ticked while being read; un-tick it to skip it
                self.analyse_q.put((iid, url))
            added += 1
        for iid in new_singles:                   # numbers are padded per folder, so label them all at the end
            L = self.links[iid]
            self.tree.item(iid, text=f"  {self._num_label(L)}{L['info']['title']}")
            self._refresh_formats(iid)
        self.links_txt.delete("1.0", "end")
        for node in self.folder_nodes.values():
            self._refresh_folder(node)
        if added:
            folders = sorted({r["folder"] for r in rows if r["folder"]}, key=self._folder_key)
            extra = f" in folder{'s' if len(folders) > 1 else ''} {', '.join(folders)}" if folders else ""
            msg = f"Added {added} link{'s' if added > 1 else ''}{extra}."
            if ready:
                msg += f" {ready} ready to download now"
                msg += f", {added - ready} being read." if added > ready else "."
            self._log(msg, "muted")
        elif not auto:
            self._log("Those links are already in the list.", "muted")
        self._refresh_summary()
        return added

    def _analyse_loop(self):
        while True:
            iid, url = self.analyse_q.get()
            if iid not in self.links:          # removed from the list while waiting
                continue
            while time.time() < self.cooldown_until and not self.skip_wait.is_set():
                time.sleep(1)                  # YouTube asked us to slow down: don't read either
            try:
                self.q.put(("analysed", iid, core.analyze(url, dict(self.cfg)), None))
            except Exception as e:  # noqa: BLE001
                self.q.put(("analysed", iid, None, core.clean_error(e)))
            time.sleep(1.0)                    # be gentle with YouTube

    def _show_link(self, iid, info, error):
        if iid not in self.links:
            return
        L = self.links[iid]
        wanted = iid in self.checked
        self.checked.discard(iid)
        if error:
            L["state"] = "error"
            self.tree.item(iid, text=f"  {L['url']}", values=("", L["folder"] or "", "", "✗ Couldn't read"),
                           tags=("link", "failed"), image=self.imgs["none"])
            self._log(f"✗ Couldn't read {L['url']}\n    {error}", "err")
            if hint := core.hint_for(error):
                self._log(f"    Tip: {hint}", "warn")
        else:
            L.update(info=info, state="ready")
            if info["kind"] == "playlist":
                single = info.get("single_id")
                big = info["count"] > 25
                self.tree.item(iid, text=f"  {self._num_label(L)}{info['title']}", tags=("link",),
                               values=("", L["folder"] or "", f"{info['count']} items", ""), open=bool(single) or not big)
                for e in info["entries"]:
                    cid = self.tree.insert(iid, "end", text=f"  {e['index']:>3}.  {e['title']}",
                                           values=("", "", core.fmt_duration(e.get("duration")), ""))
                    self.child_of[cid] = (iid, e)
                    if wanted and (not single or e.get("id") == single):
                        self.checked.add(cid)
                    if single and e.get("id") == single:
                        self.after_idle(lambda c=cid: self.tree.see(c))
                what = f"playlist '{info['title']}' ({info['count']} items)"
                if single:
                    what += " - only the video you opened is checked; tick more if you want them"
                self._log(f"✓ Loaded {what}.", "ok")
            else:
                self.tree.item(iid, text=f"  {self._num_label(L)}{info['title']}", tags=("link",),
                               values=("", L["folder"] or "", core.fmt_duration(info.get("duration")), ""))
                if wanted:
                    self.checked.add(iid)
                self._log(f"✓ Loaded '{info['title']}'.", "ok")
        self._refresh_check(iid)
        self._refresh_formats(iid)
        self._refresh_summary()
        if L.pop("auto_queue", False) and L["state"] == "ready" and wanted:
            self._enqueue(self._make_plans(only=[iid], exclude=self.in_queue))   # Download was pressed earlier

    # =========================================================================== folders
    @staticmethod
    def _folder_key(name: str):
        return (0, int(name), "") if name.isdigit() else (1, 0, name.lower())

    def _folder_node(self, folder: str) -> str:
        """The 'Folder 3' heading row, created in number order the first time it's needed."""
        if folder in self.folder_nodes:
            return self.folder_nodes[folder]
        index = "end"
        for i, top in enumerate(self.tree.get_children("")):
            other = self._folder_name(top)
            if other is None or self._folder_key(other) > self._folder_key(folder):
                index = i
                break
        node = self.tree.insert("", index, text=f"  Folder {folder}", values=("", folder, "", ""),
                                tags=("folder",), image=self.imgs["none"], open=False)
        self.folder_nodes[folder] = node
        self._folder_iids.add(node)
        return node

    def _num_label(self, L) -> str:
        p = self._prefix(L)
        return f"{p}.  " if p else ""

    def _prefix(self, L) -> str | None:
        """The CSV video number, padded to the size of the folder's biggest number ('08' of 35)."""
        if L.get("number") is None:
            return None
        largest = max((o["number"] or 0) for o in self.links.values() if o["folder"] == L["folder"])
        return core.number_prefix(L["number"], largest)

    def _folder_name(self, iid):
        return next((f for f, n in self.folder_nodes.items() if n == iid), None)

    def _is_folder(self, iid) -> bool:
        return iid in self._folder_iids

    def _links_in_order(self) -> list:
        out = []
        for top in self.tree.get_children(""):
            out.extend(self.tree.get_children(top) if self._is_folder(top) else [top])
        return [lid for lid in out if lid in self.links]

    def _refresh_folder(self, node):
        if not self.tree.exists(node):
            return
        kids = [k for k in self.tree.get_children(node) if k in self.links]
        leaves = [x for k in kids for x in self._leaves(k)]
        n = sum(1 for x in leaves if x in self.checked)
        state = "none" if not leaves else "on" if n == len(leaves) else "off" if n == 0 else "partial"
        self.tree.item(node, image=self.imgs[state])
        loading = sum(1 for k in kids if self.links[k]["state"] == "loading")
        txt = "reading…" if loading else f"{len(leaves)} video{'s' if len(leaves) != 1 else ''}"
        self.tree.set(node, "length", txt)

    def _folder_status(self, node):
        """'12 of 35 done' on a folder heading while downloading."""
        leaves = [x for k in self.tree.get_children(node) if k in self.links for x in self._leaves(k)
                  if x in self.checked]
        if not leaves:
            return
        st = [self.tree.set(x, "status") for x in leaves]
        ok = st.count("✓ Done") + st.count("Already have")
        bad = st.count("✗ Failed") + st.count("Not downloaded")
        txt = f"✓ {ok} of {len(leaves)} done" if ok == len(leaves) else f"{ok} of {len(leaves)} done"
        if bad:
            txt += f", {bad} failed"
        self.tree.set(node, "status", txt)
        if ok + bad == len(leaves):
            self.tree.item(node, tags=("folder", "failed" if bad else "done"))

    # =========================================================================== checkboxes
    def _leaves(self, iid) -> list:
        if self._is_folder(iid):
            return [x for k in self.tree.get_children(iid) if k in self.links for x in self._leaves(k)]
        L = self.links.get(iid)
        if L is None:
            return [iid]
        if L["state"] == "loading":
            return [iid]                       # stands for "whatever this link turns out to hold"
        if L["state"] != "ready":
            return []
        return list(self.tree.get_children(iid)) if L["info"]["kind"] == "playlist" else [iid]

    def _leaf_count(self, checked_only=False) -> int:
        return sum(1 for lid in self.links for leaf in self._leaves(lid) if not checked_only or leaf in self.checked)

    def _refresh_check(self, link_iid):
        if link_iid not in self.links:
            return
        leaves = self._leaves(link_iid)
        if not leaves:
            self.tree.item(link_iid, image=self.imgs["none"])
            return
        n = sum(1 for x in leaves if x in self.checked)
        state = "on" if n == len(leaves) else "off" if n == 0 else "partial"
        self.tree.item(link_iid, image=self.imgs[state])
        info = self.links[link_iid]["info"]
        if info and info["kind"] == "playlist" and self.links[link_iid]["state"] == "ready":
            for c in leaves:
                self.tree.item(c, image=self.imgs["on" if c in self.checked else "off"])
        parent = self.tree.parent(link_iid)
        if parent and self._is_folder(parent) and not getattr(self, "_bulk", False):
            self._refresh_folder(parent)

    def _is_queued(self, iid) -> bool:
        return any(x in self.in_queue for x in (self._leaves(iid) or [iid]))

    def _toggle(self, iid):
        if self._is_folder(iid):
            targets = [t for t in self._leaves(iid) if t not in self.in_queue]
            if not targets:
                return
            turn_on = not all(t in self.checked for t in targets)
            for t in targets:
                (self.checked.add if turn_on else self.checked.discard)(t)
            self._bulk = True
            for k in self.tree.get_children(iid):
                self._refresh_check(k)
            self._bulk = False
            self._refresh_folder(iid)
            self._refresh_summary()
            return
        link = self.child_of[iid][0] if iid in self.child_of else iid
        if link not in self.links or self.links[link]["state"] not in ("ready", "loading"):
            return
        targets = [t for t in self._leaves(iid) if t not in self.in_queue]   # queued ones stay as they are
        if not targets:
            return
        turn_on = not all(t in self.checked for t in targets)
        for t in targets:
            (self.checked.add if turn_on else self.checked.discard)(t)
        self._refresh_check(link)
        self._refresh_summary()

    def _on_tree_click(self, ev):
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return None
        col = self.tree.identify_column(ev.x)
        if "indicator" in str(self.tree.identify_element(ev.x, ev.y)):
            return None                    # let the expand/collapse arrow work
        if col == "#1" and iid in self.links:
            if not self._is_queued(iid):
                self._set_link_mode(iid, None)
            return "break"
        if col == "#2" and iid in self.links:
            if not self._is_queued(iid):
                self._ask_folder(iid)
            return "break"
        if col == "#0":
            self.tree.selection_set(iid)
            self._toggle(iid)
            return "break"
        return None

    def _on_tree_space(self, _ev):
        if iid := self.tree.focus():
            self._toggle(iid)
        return "break"

    def _check_all(self, on: bool):
        self._bulk = True
        for lid in self.links:
            for leaf in self._leaves(lid):
                if leaf in self.in_queue:
                    continue
                (self.checked.add if on else self.checked.discard)(leaf)
            self._refresh_check(lid)
        self._bulk = False
        for node in self.folder_nodes.values():
            self._refresh_folder(node)
        self._refresh_summary()

    def _expand_all(self, open_: bool):
        for iid in list(self.folder_nodes.values()) + list(self.links):
            self.tree.item(iid, open=open_)

    def _remove_link(self, iid):
        if iid not in self.links or (self.downloading and self._is_queued(iid)):
            return
        for c in self.tree.get_children(iid):
            self.child_of.pop(c, None)
            self.checked.discard(c)
        self.checked.discard(iid)
        self.links.pop(iid)
        parent = self.tree.parent(iid)
        self.tree.delete(iid)
        self._drop_empty_folder(parent)
        self._refresh_summary()

    def _drop_empty_folder(self, node):
        if node and self._is_folder(node):
            if self.tree.get_children(node):
                self._refresh_folder(node)
            else:
                self.folder_nodes.pop(self._folder_name(node), None)
                self._folder_iids.discard(node)
                self.tree.delete(node)

    def _remove_folder(self, node):
        for k in list(self.tree.get_children(node)):
            self._remove_link(k)

    def _remove_selected(self):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
            if self._is_folder(iid):
                self._remove_folder(iid)
            else:
                self._remove_link(self.child_of[iid][0] if iid in self.child_of else iid)

    def _clear_list(self):
        if self.downloading:
            return
        for lid in list(self.links):
            self._remove_link(lid)
        self.overall_lbl.config(text="Ready.")
        self.overall_bar["value"] = 0
        self.file_lbl.config(text="")
        self.file_bar["value"] = 0

    def _set_link_mode(self, iid, mode):
        L = self.links[iid]
        L["mode"] = mode or ("audio" if L["mode"] == "video" else "video")
        L["touched"] = True
        self._refresh_formats(iid)

    def _format_label(self, mode) -> str:
        if mode == "audio":
            return f"Audio · {self._choice(self.afmt_var).upper()}"
        q = self._choice(self.quality_var)
        return f"Video · {'Best' if q == 'best' else q + 'p'}"

    def _refresh_formats(self, only=None):
        for lid in ([only] if only else list(self.links)):
            L = self.links.get(lid)
            if L and L["state"] == "ready":
                self.tree.set(lid, "format", self._format_label(L["mode"]))

    def _refresh_summary(self):
        """Recount once the current burst of changes is done (big lists change a lot at once)."""
        if not self._summary_due:
            self._summary_due = True
            self.after(60, self._refresh_summary_now)

    def _refresh_summary_now(self):
        self._summary_due = False
        n_links = len(self.links)
        if not n_links:
            self.summary_lbl.config(text="Paste links above to begin.")
            return
        loading = sum(1 for L in self.links.values() if L["state"] == "loading")
        total, chk = self._leaf_count(), self._leaf_count(checked_only=True)
        txt = f"{n_links} link{'s' if n_links > 1 else ''}  ·  {chk} of {total} items checked"
        if self.folder_nodes:
            txt += f"  ·  {len(self.folder_nodes)} folder{'s' if len(self.folder_nodes) > 1 else ''}"
        if loading:
            txt += f"  ·  reading {loading}…"
        self.summary_lbl.config(text=txt)
        if self.downloading:
            new = sum(1 for lid in self.links for leaf in self._leaves(lid)
                      if leaf in self.checked and leaf not in self.in_queue)
            self.btn_go.config(text=f"Add to queue ({new})" if new else "Add to queue",
                               state="normal" if new else "disabled")
            waiting = len(self.in_queue - self.done_rows)
            if waiting:
                txt += f"  ·  {waiting} queued"
                self.summary_lbl.config(text=txt)
        else:
            self.btn_go.config(text=f"Download checked ({chk})" if chk else "Download checked", state="normal")

    def _on_tree_menu(self, ev):
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        m = self.menu
        m.delete(0, "end")
        state = "disabled" if self.downloading else "normal"
        if self._is_folder(iid):
            name = self._folder_name(iid)
            m.add_command(label=f"Check / uncheck folder {name}", command=lambda: self._toggle(iid), state=state)
            m.add_command(label="Download this folder as Video", state=state,
                          command=lambda: [self._set_link_mode(k, "video") for k in self.tree.get_children(iid)])
            m.add_command(label="Download this folder as Audio", state=state,
                          command=lambda: [self._set_link_mode(k, "audio") for k in self.tree.get_children(iid)])
            m.add_separator()
            m.add_command(label="Remove folder from list", command=lambda: self._remove_folder(iid), state=state)
            m.tk_popup(ev.x_root, ev.y_root)
            return
        link = self.child_of[iid][0] if iid in self.child_of else iid
        L = self.links.get(link)
        if any(p["link"] == link and not p.get("started") and not p.get("skip") for p in self.plans):
            m.add_command(label="Remove from queue", command=lambda: self._unqueue(link))
            m.add_separator()
        state = "disabled" if self._is_queued(link) else "normal"
        if L and L["state"] == "ready":
            m.add_command(label="Check / uncheck", command=lambda: self._toggle(iid), state=state)
            m.add_separator()
            m.add_command(label="Download this link as Video", state=state,
                          command=lambda: self._set_link_mode(link, "video"))
            m.add_command(label="Download this link as Audio", state=state,
                          command=lambda: self._set_link_mode(link, "audio"))
            m.add_separator()
        if L:
            m.add_command(label="Set folder…", state=state, command=lambda: self._ask_folder(link))
            if L.get("folder"):
                m.add_command(label="Clear folder", state=state, command=lambda: self._set_folder(link, None))
            m.add_separator()
        url = L["url"] if iid == link else self._entry_url(iid)
        m.add_command(label="Copy link", command=lambda: (self.clipboard_clear(), self.clipboard_append(url)))
        m.add_command(label="Open in browser", command=lambda: webbrowser.open(url))
        m.add_separator()
        m.add_command(label="Remove from list", command=lambda: self._remove_link(link), state=state)
        m.tk_popup(ev.x_root, ev.y_root)

    def _unqueue(self, link):
        """Take a link that hasn't started yet out of the download queue."""
        for p in self.plans:
            if p["link"] == link and not p.get("started") and not p.get("skip"):
                p["skip"] = True
                for r in p["rows"]:
                    self.in_queue.discard(r)
                    self.checked.discard(r)
                    self.tree.set(r, "status", "")
                if p["rows"][0] != link:
                    self.tree.set(link, "status", "")
                self.total_items -= len(p["rows"])
        self._refresh_check(link)
        self._update_overall()
        self._refresh_summary()

    def _ask_folder(self, link):
        if link not in self.links or self._is_queued(link):
            return
        L = self.links[link]
        name = simpledialog.askstring(
            APP_NAME, "Save this link's videos in which folder?\n"
                      "(e.g. 1, 2 or Songs - leave empty for the main folder)",
            initialvalue=L.get("folder") or "", parent=self)
        if name is not None:
            self._set_folder(link, core.clean_folder(name))

    def _set_folder(self, link, folder):
        old_parent = self.tree.parent(link)
        self.links[link]["folder"] = folder
        self.tree.set(link, "folder", folder or "")
        new_parent = self._folder_node(folder) if folder else ""
        if new_parent != old_parent:
            self.tree.move(link, new_parent, "end")
            self._drop_empty_folder(old_parent)
            if new_parent:
                self._refresh_folder(new_parent)
                self.tree.item(new_parent, open=True)
            self.tree.see(link)
        self._refresh_summary()

    def _entry_url(self, cid) -> str:
        link, e = self.child_of[cid]
        return f"https://www.youtube.com/watch?v={e['id']}" if e.get("id") else self.links[link]["url"]

    # =========================================================================== preview
    def _preview_structure(self):
        """Show the folders and exact file names a download of the checked items will create."""
        if core.parse_link_rows(self.links_txt.get("1.0", "end")):
            self._load_links()
        if not self.links:
            messagebox.showinfo(APP_NAME, "Paste links or import a CSV first.")
            return
        self._save_cfg()
        settings = dict(self.cfg)
        jobs, pending = [], []
        for lid in self._links_in_order():
            L = self.links[lid]
            if L["state"] == "loading":
                pending.append(L)
                continue
            if L["state"] != "ready":
                continue
            info, base = L["info"], dict(mode=L["mode"], subfolder=L["folder"], prefix=self._prefix(L))
            if info["kind"] == "video":
                if lid in self.checked:
                    title = "(YouTube title)" if info.get("provisional") else info["title"]
                    jobs.append(base | dict(title=title, video_id=info.get("id")))
                continue
            kids = [c for c in self.tree.get_children(lid) if c in self.checked]
            entries = [self.child_of[c][1] for c in kids]
            single = info.get("single_id")
            if single and len(entries) == 1 and entries[0].get("id") == single:
                jobs.append(base | dict(title=entries[0]["title"], video_id=single))
                continue
            for e in entries:
                jobs.append(base | dict(title=e["title"], video_id=e.get("id"), index=e["index"],
                                        count=info["count"], playlist_title=info["title"]))

        win = tk.Toplevel(self)
        win.title("Preview - folders and file names")
        win.transient(self)
        win.configure(bg=self.pal["bg"])
        w, h = int(820 * self.scale), int(620 * self.scale)
        win.geometry(f"{w}x{h}+{self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)}"
                     f"+{self.winfo_rooty() + 40}")
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        head = ttk.Label(frm, text="Working out file names…", style="Muted.TLabel")
        head.pack(anchor="w")
        self._preview_win = win
        self._preview_parts = (frm, head, settings, pending)

        def work():
            try:
                namer = core.FileNamer(settings)
                paths = [(namer.path(**j), j) for j in jobs]
                self.q.put(("preview", win, paths, None))
            except Exception as e:  # noqa: BLE001
                self.q.put(("preview", win, [], core.clean_error(e)))
        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, win, paths, error):
        if not win.winfo_exists():
            return
        frm, head, settings, pending = self._preview_parts
        if error:
            head.config(text=f"Couldn't work out the names: {error}")
            return
        root_dir = settings["download_dir"]
        dirs: dict = {}
        where: dict = {}
        for rel, j in paths:
            parent = rel.parent
            dirs.setdefault(parent, []).append(rel.name)
            if j.get("video_id"):
                where.setdefault(j["video_id"], set()).add(str(parent))
        repeated = sum(1 for v in where.values() if len(v) > 1)
        top = {p.parts[0] for p in dirs if p.parts}
        parts = [f"{len(paths)} file{'s' if len(paths) != 1 else ''}"]
        if top:
            parts.append(f"in {len(top)} folder{'s' if len(top) != 1 else ''}")
        if repeated:
            parts.append(f"{repeated} video{'s' if repeated != 1 else ''} saved in more than one folder")
        if pending:
            parts.append(f"{len(pending)} link{'s' if len(pending) != 1 else ''} still being read (not shown)")
        head.config(text="   ·   ".join(parts), style="TLabel")
        ttk.Label(frm, text=f"Saved under:  {root_dir}", style="Muted.TLabel").pack(anchor="w", pady=(2, 6))

        wrap = ttk.Frame(frm)
        wrap.pack(fill="both", expand=True)
        tv = ttk.Treeview(wrap, columns=("info",), selectmode="browse")
        tv.heading("#0", text="Folder / file")
        tv.heading("info", text="")
        tv.column("#0", width=int(600 * self.scale), stretch=True)
        tv.column("info", width=int(160 * self.scale), anchor="e", stretch=False)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("dir", font=(ui_font()[0], ui_font()[1], "bold"))
        tv.tag_configure("muted", foreground=self.pal["muted"])

        nodes = {Path(): ""}
        open_top = len(top) <= 3

        def node_for(d: Path):
            if d in nodes:
                return nodes[d]
            if d == d.parent:                       # safety net for odd absolute paths
                return ""
            parent = node_for(d.parent)
            nodes[d] = tv.insert(parent, "end", text=f"  {d.name}", tags=("dir",),
                                 open=open_top or len(d.parts) > 1)
            return nodes[d]
        for d in sorted(dirs, key=lambda d: [self._folder_key(x) for x in d.parts]):
            node = node_for(d)
            for name in dirs[d]:
                tv.insert(node, "end", text=f"  {name}")
            if d.parts:
                tv.set(node, "info", f"{len(dirs[d])} file{'s' if len(dirs[d]) != 1 else ''}")
        for d, node in nodes.items():                  # folders that only hold subfolders (e.g. Audio)
            if d.parts and not tv.set(node, "info"):
                n = sum(len(v) for k, v in dirs.items() if k.parts[:len(d.parts)] == d.parts)
                tv.set(node, "info", f"{n} files")
        for L in pending:
            node = node_for(Path(L["folder"])) if L["folder"] else ""
            tv.insert(node, "end", text=f"  (still reading)  {L['url']}", tags=("muted",))

        def save_txt():
            f = filedialog.asksaveasfilename(parent=win, defaultextension=".txt", initialfile="tubegrab-structure.txt",
                                             filetypes=[("Text", "*.txt")])
            if not f:
                return
            lines = [root_dir]

            def walk(item, depth):
                for c in tv.get_children(item):
                    info = tv.set(c, "info")
                    lines.append("    " * depth + tv.item(c, "text").strip() + (f"   ({info})" if info else ""))
                    walk(c, depth + 1)
            walk("", 1)
            Path(f).write_text("\n".join(lines) + "\n", "utf-8")

        bb = ttk.Frame(frm)
        bb.pack(fill="x", pady=(8, 0))
        ttk.Button(bb, text="Expand all", command=lambda: [tv.item(n, open=True) for n in nodes.values() if n]
                   ).pack(side="left")
        ttk.Button(bb, text="Collapse all", command=lambda: [tv.item(n, open=False) for n in nodes.values() if n]
                   ).pack(side="left", padx=6)
        ttk.Button(bb, text="Save as text…", command=save_txt).pack(side="left", padx=(6, 0))

        def go():
            win.destroy()
            self._download_clicked()
        ttk.Button(bb, text="Download checked", style="Accent.TButton", command=go,
                   state="disabled" if self.downloading or not paths else "normal").pack(side="right")
        ttk.Button(bb, text="Close", command=win.destroy).pack(side="right", padx=6)
        win.bind("<Escape>", lambda e: win.destroy())

    # =========================================================================== downloading
    def _download_clicked(self):
        """Download checked (or, while downloading, Add to queue). Never waits for links still being read:
        those join the queue by themselves as soon as they're ready."""
        if core.extract_urls(self.links_txt.get("1.0", "end")):
            self._load_links(auto=True)
        loading = [lid for lid, L in self.links.items() if L["state"] == "loading" and lid in self.checked]
        for lid in loading:
            self.links[lid]["auto_queue"] = True
        if not self.links:
            messagebox.showinfo(APP_NAME, "Paste one or more YouTube links in box 1 first.")
            return
        plans = self._make_plans(exclude=self.in_queue if self.downloading else frozenset())
        if plans:
            self._enqueue(plans)
        elif loading:
            self.overall_lbl.config(text=f"Reading {len(loading)} link{'s' if len(loading) > 1 else ''}… "
                                         "they start downloading by themselves.")
        elif not self.downloading:
            messagebox.showinfo(APP_NAME, "Nothing is checked. Tick what you want in the list.")

    def _make_plans(self, only=None, exclude=frozenset()) -> list:
        plans = []
        for lid in (only or self._links_in_order()):
            L = self.links[lid]
            if L["state"] != "ready":
                continue
            info, mode = L["info"], L["mode"]
            if info["kind"] == "video":
                if lid in self.checked and lid not in exclude:
                    plans.append({"link": lid, "task": core.Task(L["url"], mode, title=info["title"],
                                                               subfolder=L["folder"], prefix=self._prefix(L)),
                                  "rows": [lid], "by_index": {}, "by_id": {info.get("id"): lid}, "single": lid})
                continue
            kids = [c for c in self.tree.get_children(lid) if c in self.checked and c not in exclude]
            if not kids:
                continue
            entries = [self.child_of[c][1] for c in kids]
            single = info.get("single_id")
            if single and len(kids) == 1 and entries[0].get("id") == single:
                task = core.Task(L["url"], mode, noplaylist=True, title=entries[0]["title"],
                                 subfolder=L["folder"], prefix=self._prefix(L))
                plans.append({"link": lid, "task": task, "rows": kids, "by_index": {}, "by_id": {single: kids[0]},
                              "single": kids[0]})
                continue
            items = None if len(kids) == info["count"] else core.compress_ranges(e["index"] for e in entries)
            plans.append({"link": lid, "task": core.Task(L["url"], mode, items=items, title=info["title"],
                                                                 subfolder=L["folder"], prefix=self._prefix(L)),
                          "rows": kids, "by_index": {e["index"]: c for e, c in zip(entries, kids)},
                          "by_id": {e.get("id"): c for e, c in zip(entries, kids) if e.get("id")}, "single": None})
        return plans

    def _start_download(self):
        self._enqueue(self._make_plans())

    def _enqueue(self, plans):
        """Add downloads to the live queue, starting it if nothing is downloading yet."""
        if not plans:
            return
        self._save_cfg()
        starting = not self.downloading
        if starting:
            if not core.find_ffmpeg_dir():
                messagebox.showwarning(APP_NAME, "FFmpeg was not found.\n\nIt is needed to merge video and audio "
                                       "and to make MP3s. Run Install-Tools.bat (or put ffmpeg.exe and ffprobe.exe "
                                       "next to TubeGrab), then restart TubeGrab.")
                return
            self.plans = []
            self.in_queue = set()
            self.total_items = 0
            self.done_rows = set()
            self.counts = {"ok": 0, "skip": 0, "fail": 0, "stop": 0}
            self.cur_row, self.cur_frac = None, 0.0
            for node in self.folder_nodes.values():
                self.tree.set(node, "status", "")
                self.tree.item(node, tags=("folder",))
            self.cancel.clear()
            self.pause.clear()
            self._set_busy(True)
        settings = dict(self.cfg)
        n = 0
        with self.dl_lock:
            for p in plans:
                p["settings"] = settings
                for r in p["rows"]:
                    self.tree.set(r, "status", "Queued")
                    self.tree.item(r, tags=self._row_tags(r))
                    self.in_queue.add(r)
                if p["rows"][0] != p["link"]:
                    self.tree.set(p["link"], "status", "Queued")
                n += len(p["rows"])
                self.plans.append(p)
                self.dl_q.append(len(self.plans) - 1)
            self.total_items += n
            if not self.worker_running:
                self.worker_running = True
                threading.Thread(target=self._download_worker, daemon=True).start()
        if starting:
            self._log(f"▶ Starting {n} download{'s' if n > 1 else ''} → {self.cfg['download_dir']}", "ok")
        else:
            self._log(f"+ Added {n} to the queue.", "ok")
        self._update_overall()
        self._refresh_summary()

    COOLDOWNS = (10, 20, 30, 60)        # minutes to wait after YouTube says "slow down" (longer if it repeats)

    def _download_worker(self):
        strikes = 0
        while True:
            with self.dl_lock:
                if not self.dl_q:
                    self.worker_running = False
                    self.q.put(("all_done",))
                    return
                i = self.dl_q.popleft()
            p = self.plans[i]
            if self.cancel.is_set() or p.get("skip"):
                self.q.put(("plan_skipped", i))
                continue
            p["started"] = True
            self.q.put(("plan", i))
            result = core.download(p["task"], p["settings"], lambda k, d, i=i: self.q.put(("dl", i, k, d)),
                                   self.cancel, self.pause)
            self.q.put(("plan_done", i, result))
            if result.status != "rate_limited":
                if result.files:
                    strikes = 0
                continue
            # YouTube asked us to slow down: put this one back at the front, wait, then carry on.
            minutes = self.COOLDOWNS[min(strikes, len(self.COOLDOWNS) - 1)]
            strikes += 1
            with self.dl_lock:
                self.dl_q.appendleft(i)
            self.skip_wait.clear()
            self.cooldown_until = time.time() + minutes * 60
            self.q.put(("cooldown", minutes, result.rate_limited))
            while time.time() < self.cooldown_until and not self.cancel.is_set() and not self.skip_wait.is_set():
                time.sleep(0.5)
            self.cooldown_until = 0.0
            self.q.put(("cooldown_end",))

    def _row_for(self, plan, data):
        if plan["single"]:
            return plan["single"]
        return plan["by_id"].get(data.get("id")) or plan["by_index"].get(data.get("index")) or self.cur_row

    def _row_tags(self, row, extra=()):
        return (("link",) if row in self.links else ()) + tuple(extra)

    def _finish_row(self, row, status, kind):
        if not row or row in self.done_rows:
            return
        self.done_rows.add(row)
        self.counts[kind] += 1
        self.tree.set(row, "status", status)
        self.tree.item(row, tags=self._row_tags(row, ("done",) if kind == "ok" else
                                                     ("failed",) if kind == "fail" else ("muted",)))
        if row == self.cur_row:
            self.cur_frac = 0.0
        self._update_overall()
        self._refresh_summary()

    def _on_dl_event(self, i, kind, d):
        plan = self.plans[i]
        if kind == "item":
            row = self._row_for(plan, d)
            self.cur_row, self.cur_frac = row, 0.0
            if row and row not in self.done_rows:
                self.tree.set(row, "status", "Starting…")
                self.tree.see(row)
            self._current_title = d.get("title") or ""
            self.file_lbl.config(text=self._current_title)
            L = self.links.get(row)
            if L and L["info"].get("provisional") and d.get("title"):
                L["info"]["title"] = d["title"]
                L["info"]["provisional"] = False
                self.tree.item(row, text=f"  {self._num_label(L)}{d['title']}")
            self.file_bar["value"] = 0
        elif kind == "progress":
            row = self._row_for(plan, d)
            frac = d.get("fraction")
            if frac is not None:
                self.cur_frac = frac
                self.file_bar.config(mode="determinate")
                self.file_bar["value"] = frac * 1000
                if row and row not in self.done_rows:
                    self.tree.set(row, "status", f"Downloading {frac * 100:.0f}%")
            bits = [getattr(self, "_current_title", "")]
            if d.get("total"):
                bits.append(f"{core.fmt_bytes(d.get('downloaded'))} of {core.fmt_bytes(d['total'])}")
            if d.get("speed"):
                bits.append(f"{core.fmt_bytes(d['speed'])}/s")
            if d.get("eta") is not None:
                bits.append(f"{core.fmt_duration(d['eta'])} left")
            self.file_lbl.config(text="   ·   ".join(b for b in bits if b))
            self._update_overall()
        elif kind == "stage":
            row = self._row_for(plan, d)
            if row and row not in self.done_rows:
                self.tree.set(row, "status", d["name"] + "…")
            self.file_lbl.config(text=f"{getattr(self, '_current_title', '')}   ·   {d['name']}…")
        elif kind == "file":
            row = self._row_for(plan, d)
            self._finish_row(row, "✓ Done", "ok")
            self._log(f"✓ {Path(d['path']).name}", "ok")
            self._last_file = d["path"]
        elif kind == "skipped":
            row = plan["by_id"].get(d.get("id")) or (plan["single"] if plan["single"] else None)
            self._finish_row(row, "Already have", "skip")
            self._log(f"• Skipped {self.tree.item(row, 'text').strip() if row else d.get('id')} "
                      f"- already downloaded", "muted")
        elif kind == "error":
            row = plan["by_id"].get(d.get("id")) or plan["single"] or self.cur_row
            if row and row not in self.done_rows and row in plan["rows"]:
                self._finish_row(row, "✗ Failed", "fail")
            self._log(f"✗ {d['message']}", "err")
            if d.get("hint"):
                self._log(f"    Tip: {d['hint']}", "warn")
        elif kind == "warning":
            msg = d["message"]
            if not msg.startswith("Deprecated Feature") and "Falling back" not in msg:
                self._log(f"! {msg}", "warn")

    def _on_plan_done(self, i, result):
        plan = self.plans[i]
        if result.status == "rate_limited":         # not a failure: it goes back in the queue
            plan["started"] = False
            left = [r for r in plan["rows"] if r not in self.done_rows]
            for r in left:
                self.tree.set(r, "status", "Waiting (YouTube limit)")
            if plan["by_index"] and len(left) < len(plan["rows"]):      # playlist: retry only what's missing
                inv = {row: idx for idx, row in plan["by_index"].items()}
                plan["task"].items = core.compress_ranges(inv[r] for r in left if r in inv)
            return
        self.after_idle(lambda p=plan["link"]: self._folder_status(self.tree.parent(p))
                        if self.tree.exists(p) and self._is_folder(self.tree.parent(p)) else None)
        leftover = "Stopped" if result.status == "cancelled" else "Not downloaded"
        for r in plan["rows"]:
            if r not in self.done_rows:
                if leftover == "Not downloaded" and not result.errors and len(plan["rows"]) == 1 and result.files:
                    self._finish_row(r, "✓ Done", "ok")
                else:
                    self._finish_row(r, leftover, "fail" if leftover == "Not downloaded" else "stop")
        if plan["rows"][0] != plan["link"]:
            st = [self.tree.set(r, "status") for r in plan["rows"]]
            ok, bad = st.count("✓ Done") + st.count("Already have"), st.count("✗ Failed") + st.count("Not downloaded")
            txt = f"✓ {ok} done" if not bad else f"{ok} done, {bad} failed"
            if "Stopped" in st:
                txt = f"Stopped ({ok} done)"
            self.tree.set(plan["link"], "status", txt)
            self.tree.item(plan["link"], tags=("link", "failed" if bad else "done"))

    def _on_plan_skipped(self, i):
        plan = self.plans[i]
        if not plan.get("skip"):                 # skipped because Stop was pressed
            for r in plan["rows"]:
                self._finish_row(r, "Stopped", "stop")
            if plan["rows"][0] != plan["link"]:
                self.tree.set(plan["link"], "status", "Stopped")

    def _on_cooldown(self, minutes, message):
        self._log(f"⏸ YouTube asked TubeGrab to slow down: {message[:160]}", "warn")
        self._log(f"    Waiting {minutes} min, then carrying on by itself - nothing is lost. "
                  "Press 'Retry now' to try sooner.", "warn")
        self.btn_pause.config(text="Retry now", state="normal")
        self._tick_cooldown()

    def _tick_cooldown(self):
        if self.cooldown_until <= time.time() or not self.downloading:
            return
        self._update_overall()
        self.after(1000, self._tick_cooldown)

    def _on_all_done(self):
        with self.dl_lock:
            if self.worker_running:              # more was added after the queue ran dry: keep going
                return
        self._set_busy(False)
        c = self.counts
        parts = [f"{c['ok']} downloaded"]
        if c["skip"]:
            parts.append(f"{c['skip']} already had")
        if c["fail"]:
            parts.append(f"{c['fail']} failed")
        stopped = self.cancel.is_set()
        head = "Stopped" if stopped else "Finished"
        self.overall_lbl.config(text=f"{head}: " + ", ".join(parts) + ".")
        if not stopped:
            self.overall_bar["value"] = 1000
        self.file_lbl.config(text="")
        self.file_bar["value"] = 0
        self._log(f"■ {head}: " + ", ".join(parts) + ".", "err" if c["fail"] else "ok")
        self._refresh_summary()
        self.bell()

    def _update_overall(self):
        if not self.total_items:
            return
        if self.cooldown_until > time.time():          # the countdown wins while waiting for YouTube
            left = self.cooldown_until - time.time()
            self.overall_lbl.config(text=f"YouTube limit - waiting {core.fmt_duration(left)} before continuing   ·   "
                                         f"{self.counts['ok']} done so far")
            return
        done = len(self.done_rows)
        cur = self.cur_frac if self.cur_row and self.cur_row not in self.done_rows else 0.0
        self.overall_bar["value"] = min(1000, (done + cur) / self.total_items * 1000)
        n = min(done + 1, self.total_items)
        state = "Paused" if self.pause.is_set() else "Downloading"
        self.overall_lbl.config(text=f"{state} {n} of {self.total_items}   ·   "
                                     f"{self.counts['ok']} done" + (f", {self.counts['fail']} failed"
                                                                    if self.counts["fail"] else ""))

    def _set_busy(self, busy: bool):
        self.downloading = busy
        for w in self.option_widgets:
            try:
                if isinstance(w, ttk.Combobox):
                    w.config(state="disabled" if busy else "readonly")
                else:
                    w.config(state="disabled" if busy else "normal")
            except tk.TclError:
                pass
        for w in (self.btn_load, self.btn_paste, self.btn_import):   # links can still be added while downloading
            w.config(state="normal")
        self.links_txt.config(state="normal")
        self.btn_go.config(state="normal")
        self.btn_pause.config(state="normal" if busy else "disabled", text="Pause")
        self.btn_stop.config(state="normal" if busy else "disabled")

    def _toggle_pause(self):
        if self.cooldown_until:                  # during a YouTube cool-down this button is "Retry now"
            self.skip_wait.set()
            return
        if self.pause.is_set():
            self.pause.clear()
            self.btn_pause.config(text="Pause")
            self._log("▶ Resumed.", "muted")
        else:
            self.pause.set()
            self.btn_pause.config(text="Resume")
            self._log("Paused - press Resume to continue.", "muted")
        self._update_overall()

    def _stop(self):
        self.cancel.set()
        self.pause.clear()
        self.btn_stop.config(state="disabled")
        self.btn_pause.config(state="disabled")
        self.overall_lbl.config(text="Stopping…")

    def _open_folder(self):
        target = getattr(self, "_last_file", None)
        if not target or not Path(target).exists():
            folder = core.audio_dir(self.cfg) if self.mode_var.get() == "audio" else Path(self.cfg["download_dir"])
            if not folder.exists():
                folder = Path(self.cfg["download_dir"])
            folder.mkdir(parents=True, exist_ok=True)
            target = str(folder)
        try:
            core.open_path(target)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Couldn't open the folder:\n{e}")

    # =========================================================================== log
    def _log(self, text: str, tag: str | None = None):
        self.log_txt.config(state="normal")
        self.log_txt.insert("end", time.strftime("%H:%M:%S  "), ("muted",))
        self.log_txt.insert("end", text + "\n", (tag,) if tag else ())
        self.log_txt.see("end")
        self.log_txt.config(state="disabled")

    def _clear_log(self):
        self.log_txt.config(state="normal")
        self.log_txt.delete("1.0", "end")
        self.log_txt.config(state="disabled")

    def _save_log(self):
        f = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile="tubegrab-log.txt",
                                         filetypes=[("Text", "*.txt")])
        if f:
            Path(f).write_text(self.log_txt.get("1.0", "end"), "utf-8")

    # =========================================================================== loop
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "analysed":
                    self._show_link(*msg[1:])
                elif kind == "preview":
                    self._show_preview(*msg[1:])
                elif kind == "plan":
                    p = self.plans[msg[1]]
                    if p["rows"][0] != p["link"]:
                        self.tree.set(p["link"], "status", "Downloading…")
                        self.tree.item(p["link"], open=True)
                    parent = self.tree.parent(p["link"])
                    if self._is_folder(parent):
                        self.tree.item(parent, open=True)
                        if not self.tree.set(parent, "status"):
                            self.tree.set(parent, "status", "Downloading…")
                elif kind == "dl":
                    self._on_dl_event(*msg[1:])
                elif kind == "plan_done":
                    self._on_plan_done(*msg[1:])
                elif kind == "plan_skipped":
                    self._on_plan_skipped(*msg[1:])
                elif kind == "cooldown":
                    self._on_cooldown(*msg[1:])
                elif kind == "cooldown_end":
                    self.btn_pause.config(text="Resume" if self.pause.is_set() else "Pause",
                                          state="normal" if self.downloading else "disabled")
                    if self.downloading:
                        self._log("▶ Trying again…", "muted")
                        self._update_overall()
                elif kind == "all_done":
                    self._on_all_done()
                elif kind == "update" and msg[1]:
                    self.update_info = msg[1]
                    self.update_lbl.config(text=f"New version {msg[1]['version']} available - click to get it")
                    self._log(f"TubeGrab {msg[1]['version']} is available: {msg[1]['url']}", "ok")
                elif kind == "msg":
                    self.config(cursor="")
                    for w in self.winfo_children():
                        if isinstance(w, tk.Toplevel):
                            w.config(cursor="")
                    (messagebox.showinfo if msg[1] else messagebox.showerror)(APP_NAME, msg[2])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _startup_checks(self):
        ff = bool(core.find_ffmpeg_dir())
        js = next(iter(core.js_runtimes()), None)
        bits = [f"yt-dlp {core.ytdlp_version()}", "FFmpeg ✓" if ff else "FFmpeg missing",
                f"{js.capitalize()} ✓" if js else "Deno missing"]
        self.tools_lbl.config(text="   ·   ".join(bits), style="Muted.TLabel" if ff and js else "Warn.TLabel")
        if not ff:
            self._log("FFmpeg not found - it's needed to merge video + audio and to make MP3s. "
                      "Run Install-Tools.bat (or put ffmpeg.exe + ffprobe.exe next to TubeGrab).", "warn")
        if not js:
            self._log("Deno not found - YouTube now needs it for yt-dlp to work reliably. "
                      "Run Install-Tools.bat (winget install DenoLand.Deno).", "warn")
        self._log(f"TubeGrab {core.APP_VERSION} ready. Paste links in box 1, then press Download checked.", "muted")

    def _on_close(self):
        if self.downloading and not messagebox.askyesno(
                APP_NAME, "A download is still running.\nStop it and quit?"):
            return
        self.cancel.set()
        self.pause.clear()
        self._save_cfg()
        self.destroy()


def main():
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
