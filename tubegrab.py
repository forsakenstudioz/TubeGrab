#!/usr/bin/env python3
"""
TubeGrab - a desktop app for downloading YouTube videos, playlists and music (built on yt-dlp).

Run it with:   python tubegrab.py
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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
        self.analyse_slots = threading.Semaphore(3)
        self.auto_start = False

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
        self.btn_import = ttk.Button(bx, text="Import .txt…", command=self._import_txt)
        for b in (self.btn_load, self.btn_paste, self.btn_import):
            if self.compact:
                b.pack(side="left", padx=(0, 6))
            else:
                b.pack(side="top", fill="x", padx=6, pady=3)
        if not self.compact:
            ttk.Label(lnk, text="Videos, playlists, channels or Shorts - one per line. "
                                "Ctrl+Enter loads them; 'Download checked' also works straight away.",
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
        self.summary_lbl = ttk.Label(bar, text="Paste links above to begin.", style="Muted.TLabel")
        self.summary_lbl.pack(side="right")

        tree_wrap = ttk.Frame(tf)
        tree_wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_wrap, columns=("format", "length", "status"), selectmode="browse")
        self.tree.heading("#0", text="Video / playlist   (click to check / uncheck)")
        self.tree.heading("format", text="Format")
        self.tree.heading("length", text="Length")
        self.tree.heading("status", text="Status")
        s = self.scale
        self.tree.column("#0", width=int(520 * s), stretch=True)
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
                       cookies_browser=self._choice(cookies))
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
                text = Path(f).read_text("utf-8", errors="replace")
            except OSError as e:
                messagebox.showerror(APP_NAME, f"Couldn't read the file:\n{e}")
                return
            self.links_txt.insert("end", "\n" + text)
            self._load_links()

    def _load_links(self, auto: bool = False) -> int:
        urls = core.extract_urls(self.links_txt.get("1.0", "end"))
        if not urls:
            if not auto:
                messagebox.showinfo(APP_NAME, "Paste one or more YouTube links in the box first.")
            return 0
        known = {L["url"] for L in self.links.values()}
        added = 0
        for url in urls:
            if url in known:
                continue
            iid = self.tree.insert("", "end", text="  Reading link…", values=("", "", "Loading…"),
                                   tags=("link", "muted"), image=self.imgs["none"])
            self.links[iid] = {"url": url, "info": None, "mode": self.mode_var.get(), "touched": False,
                               "state": "loading"}
            threading.Thread(target=self._analyse_worker, args=(iid, url), daemon=True).start()
            added += 1
        self.links_txt.delete("1.0", "end")
        if added:
            self._log(f"Reading {added} link{'s' if added > 1 else ''}…", "muted")
            self.auto_start = self.auto_start or auto
        elif not auto:
            self._log("Those links are already in the list.", "muted")
        self._refresh_summary()
        return added

    def _analyse_worker(self, iid, url):
        with self.analyse_slots:
            settings = dict(self.cfg)
            try:
                self.q.put(("analysed", iid, core.analyze(url, settings), None))
            except Exception as e:  # noqa: BLE001
                self.q.put(("analysed", iid, None, core.clean_error(e)))

    def _show_link(self, iid, info, error):
        if iid not in self.links:
            return
        L = self.links[iid]
        if error:
            L["state"] = "error"
            self.tree.item(iid, text=f"  {L['url']}", values=("", "", "✗ Couldn't read"),
                           tags=("link", "failed"), image=self.imgs["none"])
            self._log(f"✗ Couldn't read {L['url']}\n    {error}", "err")
            if hint := core.hint_for(error):
                self._log(f"    Tip: {hint}", "warn")
        else:
            L.update(info=info, state="ready")
            if info["kind"] == "playlist":
                single = info.get("single_id")
                big = info["count"] > 25
                self.tree.item(iid, text=f"  {info['title']}", tags=("link",),
                               values=("", f"{info['count']} items", ""), open=bool(single) or not big)
                for e in info["entries"]:
                    cid = self.tree.insert(iid, "end", text=f"  {e['index']:>3}.  {e['title']}",
                                           values=("", core.fmt_duration(e.get("duration")), ""))
                    self.child_of[cid] = (iid, e)
                    if not single or e.get("id") == single:
                        self.checked.add(cid)
                    if single and e.get("id") == single:
                        self.after_idle(lambda c=cid: self.tree.see(c))
                what = f"playlist '{info['title']}' ({info['count']} items)"
                if single:
                    what += " - only the video you opened is checked; tick more if you want them"
                self._log(f"✓ Loaded {what}.", "ok")
            else:
                self.tree.item(iid, text=f"  {info['title']}", tags=("link",),
                               values=("", core.fmt_duration(info.get("duration")), ""))
                self.checked.add(iid)
                self._log(f"✓ Loaded '{info['title']}'.", "ok")
        self._refresh_check(iid)
        self._refresh_formats(iid)
        self._refresh_summary()
        if self.auto_start and not any(L["state"] == "loading" for L in self.links.values()):
            self.auto_start = False
            if self._leaf_count(checked_only=True):
                self._start_download()

    # =========================================================================== checkboxes
    def _leaves(self, iid) -> list:
        L = self.links.get(iid)
        if L is None:
            return [iid]
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
        if self.links[link_iid]["info"]["kind"] == "playlist":
            for c in leaves:
                self.tree.item(c, image=self.imgs["on" if c in self.checked else "off"])

    def _toggle(self, iid):
        link = self.child_of[iid][0] if iid in self.child_of else iid
        if link not in self.links or self.links[link]["state"] != "ready":
            return
        targets = self._leaves(iid)
        turn_on = not all(t in self.checked for t in targets)
        for t in targets:
            (self.checked.add if turn_on else self.checked.discard)(t)
        self._refresh_check(link)
        self._refresh_summary()

    def _on_tree_click(self, ev):
        if self.downloading:
            return "break" if self.tree.identify_region(ev.x, ev.y) != "heading" else None
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return None
        col = self.tree.identify_column(ev.x)
        if "indicator" in str(self.tree.identify_element(ev.x, ev.y)):
            return None                    # let the expand/collapse arrow work
        if col == "#1" and iid in self.links:
            self._set_link_mode(iid, None)
            return "break"
        if col == "#0":
            self.tree.selection_set(iid)
            self._toggle(iid)
            return "break"
        return None

    def _on_tree_space(self, _ev):
        if not self.downloading and (iid := self.tree.focus()):
            self._toggle(iid)
        return "break"

    def _check_all(self, on: bool):
        if self.downloading:
            return
        for lid in self.links:
            for leaf in self._leaves(lid):
                (self.checked.add if on else self.checked.discard)(leaf)
            self._refresh_check(lid)
        self._refresh_summary()

    def _expand_all(self, open_: bool):
        for lid in self.links:
            self.tree.item(lid, open=open_)

    def _remove_link(self, iid):
        if self.downloading or iid not in self.links:
            return
        for c in self.tree.get_children(iid):
            self.child_of.pop(c, None)
            self.checked.discard(c)
        self.checked.discard(iid)
        self.links.pop(iid)
        self.tree.delete(iid)
        self._refresh_summary()

    def _remove_selected(self):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
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
        n_links = len(self.links)
        if not n_links:
            self.summary_lbl.config(text="Paste links above to begin.")
            return
        loading = sum(1 for L in self.links.values() if L["state"] == "loading")
        total, chk = self._leaf_count(), self._leaf_count(checked_only=True)
        txt = f"{n_links} link{'s' if n_links > 1 else ''}  ·  {chk} of {total} items checked"
        if loading:
            txt += f"  ·  reading {loading}…"
        self.summary_lbl.config(text=txt)
        if not self.downloading:
            self.btn_go.config(text=f"Download checked ({chk})" if chk else "Download checked")

    def _on_tree_menu(self, ev):
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        link = self.child_of[iid][0] if iid in self.child_of else iid
        L = self.links.get(link)
        m = self.menu
        m.delete(0, "end")
        state = "disabled" if self.downloading else "normal"
        if L and L["state"] == "ready":
            m.add_command(label="Check / uncheck", command=lambda: self._toggle(iid), state=state)
            m.add_separator()
            m.add_command(label="Download this link as Video", state=state,
                          command=lambda: self._set_link_mode(link, "video"))
            m.add_command(label="Download this link as Audio", state=state,
                          command=lambda: self._set_link_mode(link, "audio"))
            m.add_separator()
        url = L["url"] if iid == link else self._entry_url(iid)
        m.add_command(label="Copy link", command=lambda: (self.clipboard_clear(), self.clipboard_append(url)))
        m.add_command(label="Open in browser", command=lambda: webbrowser.open(url))
        m.add_separator()
        m.add_command(label="Remove from list", command=lambda: self._remove_link(link), state=state)
        m.tk_popup(ev.x_root, ev.y_root)

    def _entry_url(self, cid) -> str:
        link, e = self.child_of[cid]
        return f"https://www.youtube.com/watch?v={e['id']}" if e.get("id") else self.links[link]["url"]

    # =========================================================================== downloading
    def _download_clicked(self):
        if self.downloading:
            return
        if core.extract_urls(self.links_txt.get("1.0", "end")):
            self._load_links(auto=True)           # starts by itself once the links are read
            self.overall_lbl.config(text="Reading links… the download starts by itself.")
            return
        if any(L["state"] == "loading" for L in self.links.values()):
            self.auto_start = True
            self.overall_lbl.config(text="Still reading links… the download starts by itself.")
            return
        if not self.links:
            messagebox.showinfo(APP_NAME, "Paste one or more YouTube links in box 1 first.")
            return
        if not self._leaf_count(checked_only=True):
            messagebox.showinfo(APP_NAME, "Nothing is checked. Tick what you want in the list.")
            return
        self._start_download()

    def _make_plans(self) -> list:
        plans = []
        for lid in self.tree.get_children(""):
            L = self.links[lid]
            if L["state"] != "ready":
                continue
            info, mode = L["info"], L["mode"]
            if info["kind"] == "video":
                if lid in self.checked:
                    plans.append({"link": lid, "task": core.Task(L["url"], mode, title=info["title"]),
                                  "rows": [lid], "by_index": {}, "by_id": {info.get("id"): lid}, "single": lid})
                continue
            kids = [c for c in self.tree.get_children(lid) if c in self.checked]
            if not kids:
                continue
            entries = [self.child_of[c][1] for c in kids]
            single = info.get("single_id")
            if single and len(kids) == 1 and entries[0].get("id") == single:
                task = core.Task(L["url"], mode, noplaylist=True, title=entries[0]["title"])
                plans.append({"link": lid, "task": task, "rows": kids, "by_index": {}, "by_id": {single: kids[0]},
                              "single": kids[0]})
                continue
            items = None if len(kids) == info["count"] else core.compress_ranges(e["index"] for e in entries)
            plans.append({"link": lid, "task": core.Task(L["url"], mode, items=items, title=info["title"]),
                          "rows": kids, "by_index": {e["index"]: c for e, c in zip(entries, kids)},
                          "by_id": {e.get("id"): c for e, c in zip(entries, kids) if e.get("id")}, "single": None})
        return plans

    def _start_download(self):
        self._save_cfg()
        plans = self._make_plans()
        if not plans:
            return
        if not core.find_ffmpeg_dir():
            messagebox.showwarning(APP_NAME, "FFmpeg was not found.\n\nIt is needed to merge video and audio "
                                   "and to make MP3s. Run Install-Tools.bat (or put ffmpeg.exe and ffprobe.exe "
                                   "next to TubeGrab), then restart TubeGrab.")
            return
        self.plans = plans
        self.total_items = sum(len(p["rows"]) for p in plans)
        self.done_rows = set()
        self.counts = {"ok": 0, "skip": 0, "fail": 0, "stop": 0}
        self.cur_row, self.cur_frac = None, 0.0
        for p in plans:
            for r in p["rows"]:
                self.tree.set(r, "status", "Queued")
                self.tree.item(r, tags=self._row_tags(r))
            if p["rows"][0] != p["link"]:
                self.tree.set(p["link"], "status", "Queued")
        self.cancel.clear()
        self.pause.clear()
        self._set_busy(True)
        n = self.total_items
        self._log(f"▶ Starting {n} download{'s' if n > 1 else ''} → {self.cfg['download_dir']}", "ok")
        settings = dict(self.cfg)
        threading.Thread(target=self._download_worker, args=(plans, settings), daemon=True).start()

    def _download_worker(self, plans, settings):
        for i, p in enumerate(plans):
            if self.cancel.is_set():
                break
            self.q.put(("plan", i))
            result = core.download(p["task"], settings, lambda k, d, i=i: self.q.put(("dl", i, k, d)),
                                   self.cancel, self.pause)
            self.q.put(("plan_done", i, result))
        self.q.put(("all_done",))

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

    def _on_all_done(self):
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
        self.links_txt.config(state="disabled" if busy else "normal")
        self.btn_go.config(state="disabled" if busy else "normal")
        self.btn_pause.config(state="normal" if busy else "disabled", text="Pause")
        self.btn_stop.config(state="normal" if busy else "disabled")

    def _toggle_pause(self):
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
                elif kind == "plan":
                    p = self.plans[msg[1]]
                    if p["rows"][0] != p["link"]:
                        self.tree.set(p["link"], "status", "Downloading…")
                        self.tree.item(p["link"], open=True)
                elif kind == "dl":
                    self._on_dl_event(*msg[1:])
                elif kind == "plan_done":
                    self._on_plan_done(*msg[1:])
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
