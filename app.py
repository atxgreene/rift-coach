"""Macro Goblin launcher: the window people open.

Starts the coach automatically (it waits for a match), shows live status, holds the
settings, lists recent match notes, and checks for updates. The overlay card and
the voice run from here; the command line (lol_coach.py) still works on its own.
"""

import argparse
import datetime
import glob
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback

import lol_coach
import settings as settings_store
import review
import updates
import voice as studio_voice
import winplat

TITLE = "Macro Goblin"

# Palette shared with the overlay: dark map glass, gold linework, restrained status colors.
BG = "#070b12"
CARD = "#0c1522"
CARD_EDGE = "#1a2a40"
RAISED = "#132033"
GOLD = "#c8aa6e"
GOLD_HI = "#f0d58c"
TEXT = "#f0e6d2"
MUTED = "#8f9bb0"
DIM = "#5d6a80"
BLUE = "#3fb7d8"
UP = "#7bd88f"
SOON = "#f0b45a"
DOWN = "#e07a7a"
TRACK_OFF = "#263245"

SPEEDS = [("Calm", 0), ("Normal", 1), ("Quick", 3)]
STYLE_CHOICES = [("Beginner", "beginner"), ("Standard", "standard"), ("Pro", "pro")]
STYLE_HELP = {"beginner": "Explains the why behind new calls.",
              "standard": "Timers, deaths, items and macro reads.",
              "pro": "Only calls that change a decision now."}
GRADE_COLORS = {"A": "#5fd38d", "B": "#c8aa6e", "C": "#e0a05a", "D": "#e06a6a"}
OBJ_NAMES = {"dragon": "Dragon", "grubs": "Void grubs", "herald": "Herald", "baron": "Baron"}
ROLE_NAMES = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "Bot", "UTILITY": "Support"}


# --------------------------------------------------------------------------- helpers
def pick_family(tkfont):
    families = set(tkfont.families())
    for name in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans"):
        if name in families:
            return name
    return "TkDefaultFont"


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kw)


def read_reports(folder, limit=4):
    """Newest match notes: [{'champion','role','result','kda','when','focus','path','grades'}]."""
    rows = []
    for path in sorted(glob.glob(os.path.join(folder, "*.md")), key=os.path.getmtime, reverse=True)[:limit]:
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        meta = dict(re.findall(r"^(\w+):\s*(.*)$", text.split("\n---", 2)[0], flags=re.M))
        kda = meta.get("kda") or (re.search(r"KDA (\d+/\d+/\d+)", text) or [None, ""])[1]
        focus = ""
        if "## Focus" in text:
            focus = text.split("## Focus", 1)[1].strip().splitlines()[0] if text.split("## Focus", 1)[1].strip() else ""
        rows.append({
            "champion": meta.get("champion", "?"),
            "role": ROLE_NAMES.get(meta.get("role", ""), ""),
            "result": (meta.get("result") or "").lower(),
            "kda": kda,
            "when": friendly_time(os.path.getmtime(path)),
            "focus": focus.replace("Next game: ", ""),
            "path": path,
            "grades": review.decode(meta.get("grades", "")),
        })
    return rows


def overall_grade(grades):
    if not grades:
        return ""
    return review.letter(sum(review.GRADE_POINTS[g] for g in grades.values()) / float(len(grades)))


def friendly_time(stamp):
    moment = datetime.datetime.fromtimestamp(stamp)
    today = datetime.date.today()
    clock = moment.strftime("%I:%M %p").lstrip("0")
    if moment.date() == today:
        return "Today " + clock
    if moment.date() == today - datetime.timedelta(days=1):
        return "Yesterday " + clock
    return moment.strftime("%b %d").replace(" 0", " ")


def next_objective(state):
    now = state.get("t")
    spawns = state.get("spawns") or {}
    if now is None or not spawns:
        return None
    key, at = min(spawns.items(), key=lambda item: item[1])
    remain = at - now
    name = "Elder" if (key == "dragon" and state.get("elder")) else OBJ_NAMES.get(key, key.title())
    if remain <= 0:
        return "%s is up" % name, UP
    return "%s in %s" % (name, lol_coach.fmt_time(remain)), (SOON if remain <= 60 else TEXT)


# --------------------------------------------------------------------------- widgets
class Switch:
    """iOS-style toggle drawn on a canvas."""

    def __init__(self, parent, value, command, px):
        import tkinter as tk
        self.px = px
        self.w, self.h = px(40), px(22)
        self.canvas = tk.Canvas(parent, width=self.w, height=self.h, bg=CARD, highlightthickness=0,
                                cursor="hand2", takefocus=1)
        self.value = bool(value)
        self.command = command
        self.canvas.bind("<Button-1>", lambda _e: self.toggle())
        self.canvas.bind("<space>", lambda _e: self.toggle())
        self.draw()

    def draw(self):
        c, w, h = self.canvas, self.w, self.h
        c.delete("all")
        round_rect(c, 1, 1, w - 1, h - 1, h / 2, fill=GOLD if self.value else TRACK_OFF, outline="")
        d = h - self.px(6)
        x = w - d - self.px(3) if self.value else self.px(3)
        c.create_oval(x, self.px(3), x + d, self.px(3) + d, fill=BG if self.value else MUTED, outline="")

    def set(self, value):
        self.value = bool(value)
        self.draw()

    def toggle(self):
        self.set(not self.value)
        self.command(self.value)


class Button:
    """Rounded button. kind: 'primary' (gold), 'ghost' (outlined), 'link' (text only)."""

    def __init__(self, parent, text, command, px, font, kind="ghost", bg=CARD, width=None):
        import tkinter as tk
        self.px, self.font, self.kind, self.bg, self.command = px, font, kind, bg, command
        self.hover = False
        self.enabled = True
        self.text = text
        tw = font.measure(text)
        self.w = width or tw + px(28 if kind != "link" else 4)
        self.h = px(34 if kind != "link" else 22)
        self.canvas = tk.Canvas(parent, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2")
        self.canvas.bind("<Enter>", lambda _e: self._hover(True))
        self.canvas.bind("<Leave>", lambda _e: self._hover(False))
        self.canvas.bind("<Button-1>", lambda _e: self.enabled and self.command())
        self.draw()

    def _hover(self, value):
        self.hover = value
        self.draw()

    def set_text(self, text):
        self.text = text
        self.draw()

    def set_enabled(self, value):
        self.enabled = value
        self.canvas.configure(cursor="hand2" if value else "arrow")
        self.draw()

    def draw(self):
        c, w, h = self.canvas, self.w, self.h
        c.delete("all")
        if self.kind == "primary":
            fill = GOLD_HI if self.hover and self.enabled else GOLD
            round_rect(c, 1, 1, w - 1, h - 1, self.px(8), fill=fill if self.enabled else TRACK_OFF, outline="")
            color = BG
        elif self.kind == "ghost":
            round_rect(c, 1, 1, w - 1, h - 1, self.px(8), fill=RAISED if self.hover else self.bg,
                       outline=GOLD if self.hover else CARD_EDGE, width=1)
            color = TEXT if self.enabled else DIM
        else:
            color = GOLD_HI if self.hover else GOLD
        c.create_text(w / 2, h / 2, text=self.text, fill=color, font=self.font)


# --------------------------------------------------------------------------- app
class LauncherApp:
    def __init__(self, args):
        import tkinter as tk
        from tkinter import font as tkfont

        self.tk = tk
        self.args = args
        self.settings = settings_store.load()
        self.session = None
        self.bus = lol_coach.UiBus()
        self.overlay_window = None
        self.overlay_stop = None
        self.release = None
        self.voices = []
        self.restart_job = None
        self.last_reports_scan = 0
        self.report_rows = None
        self.closing = False
        self.pending_installer = None
        self.ui_queue = queue.Queue()   # background threads hand UI work to tick() through this
        self.downloading = False
        self.log_path = lol_coach.data_path("logs", time.strftime("coach-%Y%m%d-%H%M%S.log"))

        winplat.enable_dpi_awareness()
        winplat.set_app_user_model_id()
        self.root = root = tk.Tk()
        root.withdraw()
        root.title(TITLE)
        root.configure(bg=BG)
        root.report_callback_exception = self.on_callback_error
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.px = lambda n: int(round(n * self.scale))
        family = pick_family(tkfont)
        self.f_title = tkfont.Font(family=family, size=15, weight="bold")
        self.f_head = tkfont.Font(family=family, size=12, weight="bold")
        self.f_body = tkfont.Font(family=family, size=10)
        self.f_bold = tkfont.Font(family=family, size=10, weight="bold")
        self.f_small = tkfont.Font(family=family, size=9)
        self.f_tiny = tkfont.Font(family=family, size=8, weight="bold")
        self.f_mono = tkfont.Font(family="Consolas" if "Consolas" in tkfont.families() else "DejaVu Sans Mono",
                                  size=15, weight="bold")
        self._icons()
        self.build()
        root.update_idletasks()
        self.refresh_reports()
        self.refresh_status()
        root.update_idletasks()
        width = self.content.winfo_reqwidth()
        height = min(self.content.winfo_reqheight(), root.winfo_screenheight() - self.px(80))
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 3)
        root.geometry("%dx%d+%d+%d" % (width, height, x, y))
        root.resizable(False, False)  # the window always fits its content
        root.protocol("WM_DELETE_WINDOW", self.request_close)
        root.deiconify()
        winplat.dark_title_bar(root)
        if args.minimized:
            root.iconify()

        self.start_session(demo=args.demo)
        if self.settings["overlay"]:
            self.show_overlay(True)
        root.after(250, self.tick)
        if self.settings["check_updates"] and not args.no_update_check:
            root.after(2500, lambda: threading.Thread(target=self.check_updates, daemon=True).start())
        threading.Thread(target=self.load_voices, daemon=True).start()

    # ----- assets
    def _icons(self):
        tk = self.tk
        self.logo = None
        ico = os.path.join(lol_coach.ROOT, "assets", "app-icon.ico")
        if winplat.IS_WIN and os.path.exists(ico):
            try:
                self.root.iconbitmap(default=ico)
            except tk.TclError:
                pass
        for name in ("app-icon-256.png", "app-icon-128.png", "live-mark-128.png"):
            path = os.path.join(lol_coach.ROOT, "assets", name)
            if os.path.exists(path):
                try:
                    image = tk.PhotoImage(file=path)
                    self.root.iconphoto(True, image)
                    self._icon_ref = image
                    break
                except tk.TclError:
                    continue
        path = os.path.join(lol_coach.ROOT, "assets", "live-mark-128.png")
        if os.path.exists(path):
            try:
                full = tk.PhotoImage(file=path)
                factor = max(1, int(round(full.width() / float(self.px(46)))))
                self.logo = full.subsample(factor, factor)
                self._logo_full = full
            except tk.TclError:
                self.logo = None

    # ----- layout
    def card(self, parent, title=None, action=None, before=None):
        tk, px = self.tk, self.px
        outer = tk.Frame(parent, bg=BG)
        options = {"fill": "x", "pady": (0, px(12))}
        if before is not None:
            options["before"] = before
        outer.pack(**options)
        frame = tk.Frame(outer, bg=CARD, highlightbackground=CARD_EDGE, highlightthickness=1)
        frame.pack(fill="x")
        body = tk.Frame(frame, bg=CARD, padx=px(16), pady=px(14))
        body.pack(fill="x")
        if title:
            head = tk.Frame(body, bg=CARD)
            head.pack(fill="x", pady=(0, px(8)))
            tk.Label(head, text=title, bg=CARD, fg=MUTED, font=self.f_tiny).pack(side="left")
            if action:
                text, command = action
                Button(head, text, command, px, self.f_small, kind="link").canvas.pack(side="right")
        return outer, body

    def build(self):
        tk, px = self.tk, self.px
        root = self.root
        self.content = content = tk.Frame(root, bg=BG)
        content.pack(fill="both", expand=True)

        # Footer first, so it keeps its space if the window is ever shorter than the content.
        footer = tk.Frame(content, bg=BG, padx=px(18), pady=px(8))
        footer.pack(fill="x", side="bottom")
        for text, command in (("Help", lambda: winplat.open_url(lol_coach.REPO_URL + "#readme")),
                              ("Troubleshooting", lambda: winplat.open_url(
                                  lol_coach.REPO_URL + "/blob/main/docs/TROUBLESHOOTING.md")),
                              ("Data folder", lambda: winplat.open_path(lol_coach.DATA)),
                              ("Check for updates", self.manual_update_check)):
            Button(footer, text, command, px, self.f_small, kind="link", bg=BG).canvas.pack(side="left",
                                                                                          padx=(0, px(14)))
        self.footer_note = tk.Label(footer, text="Read-only  \u00b7  Riot's local game API only", bg=BG, fg=DIM,
                                    font=self.f_small)
        self.footer_note.pack(side="right")

        # Header
        header = tk.Frame(content, bg=BG, padx=px(18), pady=px(14))
        header.pack(fill="x")
        if self.logo is not None:
            tk.Label(header, image=self.logo, bg=BG).pack(side="left", padx=(0, px(12)))
        names = tk.Frame(header, bg=BG)
        names.pack(side="left")
        tk.Label(names, text=TITLE, bg=BG, fg=GOLD_HI, font=self.f_title).pack(anchor="w")
        tk.Label(names, text="Live macro coach for League of Legends", bg=BG, fg=MUTED,
                 font=self.f_small).pack(anchor="w")
        tk.Label(header, text="v%s" % lol_coach.__version__, bg=RAISED, fg=MUTED, font=self.f_tiny,
                 padx=px(8), pady=px(3)).pack(side="right", anchor="n", pady=px(4))
        self.header = header

        # Update banner slot (hidden until needed)
        self.banner = tk.Frame(content, bg=BG)
        self.banner_inner = None

        columns = tk.Frame(content, bg=BG, padx=px(18))
        columns.pack(fill="both", expand=True)
        self.left = left = tk.Frame(columns, bg=BG)
        left.pack(side="left", fill="y", anchor="n")
        tk.Frame(columns, bg=BG, width=px(12)).pack(side="left")
        self.right = right = tk.Frame(columns, bg=BG)
        right.pack(side="left", fill="y", anchor="n")

        # Status
        self.status_outer, status = self.card(left)
        top = tk.Frame(status, bg=CARD)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=px(12), height=px(12), bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, px(8)))
        self.status_title = tk.Label(top, text="STARTING", bg=CARD, fg=TEXT, font=self.f_head)
        self.status_title.pack(side="left")
        self.clock = tk.Label(top, text="", bg=CARD, fg=TEXT, font=self.f_mono)
        self.clock.pack(side="right")
        self.status_line = tk.Label(status, text="", bg=CARD, fg=MUTED, font=self.f_body, anchor="w",
                                    justify="left", wraplength=px(360))
        self.status_line.pack(fill="x", pady=(px(6), 0))
        self.status_meta = tk.Label(status, text="", bg=CARD, fg=GOLD_HI, font=self.f_bold, anchor="w",
                                    justify="left", wraplength=px(360))
        self.last_call = tk.Label(status, text="", bg=CARD, fg=TEXT, font=self.f_small, anchor="w",
                                  justify="left", wraplength=px(360))
        self.actions = actions = tk.Frame(status, bg=CARD)
        actions.pack(fill="x", pady=(px(12), 0))
        self.btn_power = Button(actions, "Pause coach", self.toggle_session, px, self.f_bold, kind="ghost",
                                width=px(150))
        self.btn_power.canvas.pack(side="left")
        self.btn_demo = Button(actions, "Watch a demo", self.toggle_demo, px, self.f_bold, kind="ghost",
                               width=px(150))
        self.btn_demo.canvas.pack(side="left", padx=(px(8), 0))
        tk.Frame(status, bg=CARD, width=px(362), height=1).pack()  # fixes the column width

        # Matches
        _outer, self.matches = self.card(left, "RECENT MATCHES",
                                         action=("Open folder", lambda: winplat.open_path(lol_coach.data_path("reports"))))

        # Trends across saved match notes
        _outer, self.trends = self.card(left, "YOUR TRENDS")

        # Welcome (first run) sits above status
        self.welcome = None
        if not self.settings.get("first_run_done"):
            self.build_welcome(left)

        # Settings
        _outer, box = self.card(right, "COACH")
        self.switches = {}
        self.setting_row(box, "voice", "Voice callouts", "Timers, deaths and item calls.")
        self.voice_row = tk.Frame(box, bg=CARD)
        self.voice_row.pack(fill="x", pady=(0, px(12)))
        self.voice_label = tk.Label(self.voice_row, text=self.voice_display(), bg=RAISED, fg=TEXT,
                                    font=self.f_small, padx=px(10), pady=px(5), cursor="hand2")
        self.voice_label.pack(side="left")
        self.voice_label.bind("<Button-1>", self.pick_voice)
        self.speed_labels = []
        speeds = tk.Frame(self.voice_row, bg=CARD)
        speeds.pack(side="left", padx=(px(6), 0))
        for name, rate in SPEEDS:
            lbl = tk.Label(speeds, text=name, bg=CARD, fg=MUTED, font=self.f_small, padx=px(7), pady=px(5),
                           cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, r=rate: self.set_speed(r))
            self.speed_labels.append((lbl, rate))
        self.paint_speeds()
        Button(self.voice_row, "Test", self.test_voice, px, self.f_small, kind="ghost").canvas.pack(side="right")

        # Coach style: segmented Beginner / Standard / Pro
        style_row = tk.Frame(box, bg=CARD)
        style_row.pack(fill="x", pady=(0, px(12)))
        text = tk.Frame(style_row, bg=CARD)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text="Coach style", bg=CARD, fg=TEXT, font=self.f_bold, anchor="w").pack(fill="x")
        self.style_help = tk.Label(text, text="", bg=CARD, fg=MUTED, font=self.f_small, anchor="w",
                                   justify="left", wraplength=px(190))
        self.style_help.pack(fill="x")
        seg = tk.Frame(style_row, bg=RAISED)
        seg.pack(side="right", anchor="n")
        self.style_labels = []
        for name, key in STYLE_CHOICES:
            lbl = tk.Label(seg, text=name, bg=RAISED, fg=MUTED, font=self.f_small, padx=px(8), pady=px(5),
                           cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, k=key: self.set_style(k))
            self.style_labels.append((lbl, key))
        self.paint_style()

        # Which kinds of callouts are spoken
        mute_row = tk.Frame(box, bg=CARD)
        mute_row.pack(fill="x", pady=(0, px(12)))
        text = tk.Frame(mute_row, bg=CARD)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text="Spoken callouts", bg=CARD, fg=TEXT, font=self.f_bold, anchor="w").pack(fill="x")
        self.mute_help = tk.Label(text, text="", bg=CARD, fg=MUTED, font=self.f_small, anchor="w")
        self.mute_help.pack(fill="x")
        self.mute_button = tk.Label(mute_row, text="Choose  \u25be", bg=RAISED, fg=TEXT, font=self.f_small,
                                    padx=px(10), pady=px(5), cursor="hand2")
        self.mute_button.pack(side="right", anchor="n")
        self.mute_button.bind("<Button-1>", self.pick_mutes)
        self.paint_mutes()
        self.setting_row(box, "hotkeys", "Quick keys", "Ctrl+Shift+R repeats the last call. Ctrl+Shift+N says what's next.")
        self.setting_row(box, "overlay", "On-screen overlay", "Ctrl+Shift+O hides it.  Ctrl+Shift+M moves it.")
        self.setting_row(box, "capture", "Record my matches", "Stays on this PC. Powers your match notes.")
        self.setting_row(box, "web", "Second-screen dashboard", "Live timers in your browser.",
                         extra=("Open", lambda: winplat.open_url("http://127.0.0.1:8765")))
        start_value = winplat.autostart_enabled() if winplat.IS_WIN else self.settings["start_with_windows"]
        self.setting_row(box, "start_with_windows", "Start with Windows", "Opens minimized, ready before you queue.",
                         value=start_value, last=True)
        tk.Frame(box, bg=CARD, width=px(330), height=1).pack()


    def build_welcome(self, parent):
        tk, px = self.tk, self.px
        self.welcome, body = self.card(parent, "WELCOME", before=self.status_outer)
        tk.Label(body, text="You're set. Just play.", bg=CARD, fg=TEXT, font=self.f_head, anchor="w").pack(fill="x")
        tips = ("Set League to Borderless (Settings > Video > Window Mode) so the overlay can show. "
                "Leave this open; the coach connects by itself when your match loads.")
        tk.Label(body, text=tips, bg=CARD, fg=MUTED, font=self.f_body, justify="left", anchor="w",
                 wraplength=px(360)).pack(fill="x", pady=(px(4), px(10)))
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        Button(row, "Got it", self.dismiss_welcome, px, self.f_bold, kind="primary", width=px(110)).canvas.pack(
            side="left")
        Button(row, "Watch a demo first", self.welcome_demo, px, self.f_bold, kind="ghost").canvas.pack(
            side="left", padx=(px(8), 0))

    def setting_row(self, parent, key, title, sub, value=None, extra=None, last=False):
        tk, px = self.tk, self.px
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 0 if last else px(12)))
        text = tk.Frame(row, bg=CARD)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=CARD, fg=TEXT, font=self.f_bold, anchor="w").pack(fill="x")
        tk.Label(text, text=sub, bg=CARD, fg=MUTED, font=self.f_small, anchor="w", justify="left",
                 wraplength=px(250)).pack(fill="x")
        switch = Switch(row, self.settings.get(key) if value is None else value,
                        lambda v, k=key: self.on_setting(k, v), px)
        switch.canvas.pack(side="right", padx=(px(8), 0))
        if extra:
            Button(row, extra[0], extra[1], px, self.f_small, kind="link").canvas.pack(side="right")
        self.switches[key] = switch
        return row

    # ----- settings
    def voice_display(self):
        name = self.settings.get("voice_name") or ""
        if studio_voice.is_studio(name) or (not name and studio_voice.available()):
            vid = studio_voice.resolve(name)
            if vid:
                return "\u2605 %s (Studio)  \u25be" % studio_voice.label(vid)
            name = ""
        name = (name or "Default voice").replace("Microsoft ", "").replace(" Desktop", "")
        return "%s  \u25be" % name

    def paint_style(self):
        current = self.settings.get("coach_style", "standard")
        for lbl, key in self.style_labels:
            active = key == current
            lbl.configure(bg=GOLD if active else RAISED, fg=BG if active else MUTED)
        self.style_help.configure(text=STYLE_HELP.get(current, ""))

    def set_style(self, key):
        if key == self.settings.get("coach_style"):
            return
        self.settings["coach_style"] = key
        self.paint_style()
        self.apply_live()

    def paint_mutes(self):
        muted = [k for k in self.settings.get("muted", []) if k in lol_coach.CATEGORIES]
        if not muted:
            text = "All kinds on. Muted ones still show on the overlay."
        elif len(muted) == 1:
            text = "%s muted." % lol_coach.CATEGORIES[muted[0]]
        else:
            text = "%d kinds muted." % len(muted)
        self.mute_help.configure(text=text)

    def pick_mutes(self, event):
        tk = self.tk
        menu = tk.Menu(self.root, tearoff=0, bg=RAISED, fg=TEXT, activebackground=GOLD, activeforeground=BG,
                       selectcolor=GOLD_HI, font=self.f_small, bd=0)
        muted = set(self.settings.get("muted", []))
        self._mute_vars = {}
        for key, label in lol_coach.CATEGORIES.items():
            var = tk.BooleanVar(value=key not in muted)
            self._mute_vars[key] = var
            menu.add_checkbutton(label=label, variable=var, command=lambda k=key: self.toggle_mute(k))
        menu.tk_popup(event.x_root, event.y_root)

    def toggle_mute(self, key):
        muted = [k for k in self.settings.get("muted", []) if k != key]
        if not self._mute_vars[key].get():
            muted.append(key)
        self.settings["muted"] = muted
        self.paint_mutes()
        self.apply_live()

    def apply_live(self):
        """Style and mutes change the running coach directly; no restart, nothing re-announced."""
        settings_store.save(self.settings)
        coach = self.session.coach if self.session else None
        if coach is None:
            self.save_and_restart()
            return
        coach.style = self.settings["coach_style"]
        coach.muted = set(self.settings["muted"])
        self.session.options.coach_style = coach.style
        self.session.options.muted = list(coach.muted)

    def paint_speeds(self):
        current = int(self.settings.get("voice_rate", 1))
        for lbl, rate in self.speed_labels:
            active = rate == current
            lbl.configure(bg=RAISED if active else CARD, fg=GOLD_HI if active else MUTED)

    def set_speed(self, rate):
        self.settings["voice_rate"] = rate
        self.paint_speeds()
        self.save_and_restart()

    def load_voices(self):
        self.voices = lol_coach.Speaker.list_voices()

    def pick_voice(self, event):
        tk = self.tk
        menu = tk.Menu(self.root, tearoff=0, bg=RAISED, fg=TEXT, activebackground=GOLD, activeforeground=BG,
                       font=self.f_small, bd=0)
        studio = studio_voice.installed()
        if studio:
            menu.add_command(label="Studio voices (natural, offline)", state="disabled")
            for vid in studio:
                desc = studio_voice.VOICES.get(vid, ("", ""))[1]
                menu.add_command(label="  \u2605 %s  %s" % (studio_voice.label(vid), desc),
                                 command=lambda v=vid: self.set_voice(studio_voice.PREFIX + v))
            for vid, row in studio_voice.VOICES.items():
                if vid not in studio and studio_voice.piper_exe():
                    menu.add_command(label="  + Get %s  %s (%d MB)" % (row[0], row[1], row[4]),
                                     command=lambda v=vid: self.get_voice(v))
            menu.add_separator()
            menu.add_command(label="Windows voices", state="disabled")
        for name in list(self.voices) or ([] if studio else [""]):
            label = (name or "Default voice").replace("Microsoft ", "").replace(" Desktop", "")
            menu.add_command(label="  " + label, command=lambda n=name: self.set_voice(n))
        if not self.voices:
            menu.add_command(label="  (more voices: Windows Settings > Time & language > Speech)", state="disabled")
        menu.tk_popup(event.x_root, event.y_root)

    def get_voice(self, vid):
        if getattr(self, "voice_download", None):
            return
        self.voice_download = vid
        name = studio_voice.label(vid)
        self.flash_status("Downloading the %s voice..." % name)

        def progress(frac):
            self.ui(lambda f=frac: self.voice_label.configure(text="Downloading %s  %d%%" % (name, f * 100)))

        def work():
            try:
                studio_voice.download_voice(vid, progress)
                self.ui(lambda: self.voice_ready(vid, None))
            except Exception as exc:
                msg = "%s" % type(exc).__name__
                self.ui(lambda m=msg: self.voice_ready(vid, m))

        threading.Thread(target=work, daemon=True).start()

    def voice_ready(self, vid, error):
        self.voice_download = None
        if error:
            self.voice_label.configure(text=self.voice_display())
            self.flash_status("Couldn't download that voice (%s). Check your connection." % error)
            return
        self.flash_status("%s is ready." % studio_voice.label(vid))
        self.set_voice(studio_voice.PREFIX + vid)

    def set_voice(self, name):
        self.settings["voice_name"] = name
        self.voice_label.configure(text=self.voice_display())
        self.save_and_restart()

    def test_voice(self):
        speaker = self.session.speaker if self.session and self.session.speaker else None
        if speaker and speaker.mode:
            speaker.say("Macro Goblin here. Dragon in 60 seconds.", lol_coach.P_URGENT)
            self.flash_status("Playing: %s" % speaker.engine)
        else:
            self.flash_status("Voice is off. Turn on Voice callouts to hear it.")

    def on_setting(self, key, value):
        if key == "start_with_windows":
            ok = winplat.set_autostart(value) if winplat.IS_WIN else True
            if not ok:
                self.switches[key].set(not value)
                self.flash_status("Windows blocked the startup setting.")
                return
            self.settings[key] = value
            settings_store.save(self.settings)
            return
        self.settings[key] = value
        if key == "overlay":
            settings_store.save(self.settings)
            self.show_overlay(value)
            return
        self.save_and_restart()

    def save_and_restart(self):
        settings_store.save(self.settings)
        if self.restart_job:
            self.root.after_cancel(self.restart_job)
        # Debounced: several clicks in a row cause one restart.
        self.restart_job = self.root.after(500, self.restart_session)

    # ----- session
    def options(self, demo=False):
        s = self.settings
        return lol_coach.SessionOptions(
            demo=demo, speed=12 if demo else 10, voice=s["voice"], voice_name=s["voice_name"],
            voice_rate=s["voice_rate"], voice_volume=s["voice_volume"], capture=s["capture"] and not demo,
            log=not demo, log_path=self.log_path, web=s["web"], me=s["summoner"] or None,
            cs_target=s["cs_target"], coach_style=s["coach_style"], muted=s["muted"],
            hotkeys=s["hotkeys"] and not demo,
        )

    def start_session(self, demo=False):
        self.stop_session()
        self.session = lol_coach.CoachSession(self.options(demo=demo), bus=self.bus).start()
        self.demo_mode = demo

    def stop_session(self, wait=False):
        if self.session:
            session, self.session = self.session, None
            if wait:
                session.stop(timeout=6)   # on quit: make sure the match note is written
            else:
                session.stop_in_background()
            lol_coach.publish_idle(self.bus)

    def restart_session(self):
        self.restart_job = None
        if self.session is not None:
            self.start_session(demo=getattr(self, "demo_mode", False))

    def toggle_session(self):
        if self.session:
            self.stop_session()
        else:
            self.start_session()

    def toggle_demo(self):
        if self.session and getattr(self, "demo_mode", False):
            self.start_session(demo=False)
        else:
            self.start_session(demo=True)

    def welcome_demo(self):
        self.dismiss_welcome()
        self.start_session(demo=True)

    def dismiss_welcome(self):
        self.settings["first_run_done"] = True
        settings_store.save(self.settings)
        if self.welcome is not None:
            self.welcome.destroy()
            self.welcome = None
            self.fit_height()

    def fit_height(self):
        """Resize to the content (fonts differ per PC) and keep the whole window on screen."""
        root = self.root
        root.update_idletasks()
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        height = min(self.content.winfo_reqheight(), screen_h - self.px(80))
        width = min(max(root.winfo_width(), self.content.winfo_reqwidth()), screen_w)
        x = min(max(0, root.winfo_x()), max(0, screen_w - width))
        y = min(max(0, root.winfo_y()), max(0, screen_h - height - self.px(48)))
        root.geometry("%dx%d+%d+%d" % (width, height, x, y))

    # ----- overlay
    def show_overlay(self, on):
        if self.overlay_stop is not None:
            self.overlay_stop.set()
            self.overlay_stop = None
            self.overlay_window = None
        if not on:
            return
        try:
            import overlay
            self.overlay_stop = threading.Event()
            self.overlay_window = overlay.run(self.bus, self.overlay_stop, master=self.root)
        except Exception as exc:
            self.overlay_stop = None
            self.flash_status("Overlay could not start (%s)." % exc)

    # ----- live view
    def flash_status(self, text):
        self.last_call.configure(text=text, fg=SOON)
        self.flash_until = time.time() + 6

    def set_dot(self, color):
        self.dot.delete("all")
        self.dot.create_oval(1, 1, self.px(11), self.px(11), fill=color, outline="")

    def ui(self, fn):
        """Run fn on the Tk thread. Safe to call from any thread, even while closing."""
        self.ui_queue.put(fn)

    def tick(self):
        if self.closing:
            return
        while True:
            try:
                fn = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                write_crash(*sys.exc_info())
        try:
            self.refresh_status()
            if time.time() - self.last_reports_scan > 4:
                self.last_reports_scan = time.time()
                self.refresh_reports()
            if os.environ.get("MACROGOBLIN_DEBUG_LAYOUT") and getattr(self, "_debug_ticks", 0) < 12:
                self._debug_ticks = getattr(self, "_debug_ticks", 0) + 1
                print("layout: win %dx%d req %dx%d left %d right %d screen %d state %s scale %.2f" % (
                    self.root.winfo_width(), self.root.winfo_height(), self.content.winfo_reqwidth(),
                    self.content.winfo_reqheight(), self.left.winfo_reqwidth(), self.right.winfo_reqwidth(),
                    self.root.winfo_screenwidth(), self.root.state(), self.scale), flush=True)
            want_h = min(self.content.winfo_reqheight(), self.root.winfo_screenheight() - self.px(80))
            want_w = self.content.winfo_reqwidth()
            if self.root.state() == "normal" and (abs(self.root.winfo_height() - want_h) > 2
                                                  or self.root.winfo_width() < want_w):
                self.fit_height()
        finally:
            self.root.after(250, self.tick)

    def refresh_status(self):
        state = self.bus.snapshot()
        session = self.session
        demo = bool(session and getattr(self, "demo_mode", False))
        if session is None:
            self.set_dot(DIM)
            self.status_title.configure(text="PAUSED", fg=MUTED)
            self.clock.configure(text="")
            self.status_line.configure(text="The coach is off. Start it before you queue.")
            self.status_meta.configure(text="")
            self.show_label(self.status_meta, False)
            self.btn_power.set_text("Start coach")
        elif session.error:
            self.set_dot(DOWN)
            self.status_title.configure(text="STOPPED", fg=DOWN)
            self.status_line.configure(text="Something went wrong: %s" % session.error)
            self.btn_power.set_text("Restart coach")
        elif state.get("in_game"):
            self.set_dot(BLUE if demo else UP)
            self.status_title.configure(text="DEMO" if demo else "LIVE", fg=BLUE if demo else UP)
            self.clock.configure(text=state.get("clock") or "")
            bits = [state.get("champion"), ROLE_NAMES.get(state.get("position") or "", ""), state.get("kda"),
                    ("Lvl %s" % state["level"]) if state.get("level") else ""]
            self.status_line.configure(text="  ·  ".join(bit for bit in bits if bit), fg=TEXT)
            meta = []
            nxt = next_objective(state)
            if nxt:
                meta.append(nxt[0])
            dragons = state.get("dragons") or {}
            if dragons.get("us") or dragons.get("them"):
                meta.append("Dragons %d–%d" % (dragons.get("us", 0), dragons.get("them", 0)))
            if state.get("gold_ok", True) and state.get("t", 0) >= 240:
                diff = state.get("gold_diff") or 0
                meta.append("Gold %s%.1fk" % ("+" if diff >= 0 else "−", abs(diff) / 1000.0))
            self.status_meta.configure(text="   \u00b7   ".join(meta), fg=nxt[1] if nxt else GOLD_HI)
            self.show_label(self.status_meta, bool(meta))
            self.btn_power.set_text("Pause coach")
        else:
            self.set_dot(SOON)
            self.status_title.configure(text="WAITING FOR A MATCH", fg=TEXT)
            self.clock.configure(text="")
            self.status_line.configure(text="Start League. The coach connects by itself when your match loads.",
                                       fg=MUTED)
            self.status_meta.configure(text="")
            self.show_label(self.status_meta, False)
            self.btn_power.set_text("Pause coach")
        self.btn_demo.set_text("Stop demo" if demo else "Watch a demo")
        if time.time() > getattr(self, "flash_until", 0):
            calls = state.get("callouts") or []
            text = ("\u201c%s\u201d" % calls[-1][1]) if calls and state.get("in_game") else ""
            self.last_call.configure(text=text, fg=TEXT)
        self.show_label(self.last_call, bool(self.last_call.cget("text")))

    def show_label(self, label, visible):
        mapped = bool(label.winfo_manager())
        if visible and not mapped:
            label.pack(fill="x", pady=(self.px(5), 0), before=self.actions)
        elif not visible and mapped:
            label.pack_forget()

    def refresh_reports(self):
        tk, px = self.tk, self.px
        history = read_reports(lol_coach.data_path("reports"), limit=20)
        rows = history[:4]
        signature = [(row["path"], row["result"], len(history)) for row in rows]
        if signature == self.report_rows:
            return
        self.report_rows = signature
        self.render_trends(history)
        for child in self.matches.winfo_children()[1:]:
            child.destroy()
        if not rows:
            tk.Label(self.matches, text="Your match notes show up here after your first game.", bg=CARD, fg=MUTED,
                     font=self.f_small, anchor="w").pack(fill="x")
            return
        for idx, row in enumerate(rows):
            line = tk.Frame(self.matches, bg=CARD, cursor="hand2")
            line.pack(fill="x", pady=(0 if idx == 0 else px(8), 0))
            head = tk.Frame(line, bg=CARD)
            head.pack(fill="x")
            tk.Label(head, text=row["champion"], bg=CARD, fg=TEXT, font=self.f_bold).pack(side="left")
            if row["role"]:
                tk.Label(head, text=row["role"], bg=CARD, fg=MUTED, font=self.f_small).pack(side="left",
                                                                                         padx=(px(6), 0))
            result = {"win": ("WIN", UP), "loss": ("LOSS", DOWN)}.get(row["result"])
            if result:
                tk.Label(head, text=result[0], bg=CARD, fg=result[1], font=self.f_tiny).pack(side="left",
                                                                                         padx=(px(8), 0))
            if row["kda"]:
                tk.Label(head, text=row["kda"], bg=CARD, fg=TEXT, font=self.f_small).pack(side="left",
                                                                                       padx=(px(8), 0))
            tk.Label(head, text=row["when"], bg=CARD, fg=DIM, font=self.f_small).pack(side="right")
            grade = overall_grade(row.get("grades"))
            if grade:
                tk.Label(head, text=grade, bg=RAISED, fg=GRADE_COLORS[grade], font=self.f_tiny,
                         padx=px(5)).pack(side="right", padx=(0, px(8)))
            if row["focus"]:
                tk.Label(line, text=row["focus"], bg=CARD, fg=MUTED, font=self.f_small, anchor="w").pack(fill="x")
            for widget in [line, head] + list(line.winfo_children()) + list(head.winfo_children()):
                widget.bind("<Button-1>", lambda _e, p=row["path"]: winplat.open_path(p))
        self.fit_height()

    def render_trends(self, history):
        tk, px = self.tk, self.px
        box = self.trends
        for child in box.winfo_children()[1:]:
            child.destroy()
        games = [{"champion": r["champion"], "result": r["result"], "grades": r.get("grades") or {}} for r in history]
        info = review.trends(games)
        if info["wins"] + info["losses"] < 2:
            tk.Label(box, text="Play a couple of games and your record, best champions and the one thing to "
                               "work on show up here.", bg=CARD, fg=MUTED, font=self.f_small, anchor="w",
                     justify="left", wraplength=px(360)).pack(fill="x")
            return
        top = tk.Frame(box, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text="%dW  %dL" % (info["wins"], info["losses"]), bg=CARD, fg=TEXT,
                 font=self.f_head).pack(side="left")
        tk.Label(top, text="last %d games" % (info["wins"] + info["losses"]), bg=CARD, fg=MUTED,
                 font=self.f_small).pack(side="left", padx=(px(8), 0), pady=(px(4), 0))
        if info["streak"]:
            tk.Label(top, text=info["streak"], bg=CARD, fg=UP if "win" in info["streak"] else DOWN,
                     font=self.f_small).pack(side="right", pady=(px(4), 0))
        champs = "   ".join("%s %d-%d" % row for row in info["champions"][:3])
        if champs:
            tk.Label(box, text=champs, bg=CARD, fg=MUTED, font=self.f_small, anchor="w").pack(fill="x",
                                                                                         pady=(px(2), px(8)))
        if info["averages"]:
            grid = tk.Frame(box, bg=CARD)
            grid.pack(fill="x")
            for col, area in enumerate(a for a in review.AREAS if a in info["averages"]):
                grade = review.letter(info["averages"][area])
                cell = tk.Frame(grid, bg=RAISED, padx=px(6), pady=px(4))
                cell.grid(row=0, column=col, padx=(0, px(6)), sticky="w")
                tk.Label(cell, text=grade, bg=RAISED, fg=GRADE_COLORS[grade], font=self.f_bold).pack()
                tk.Label(cell, text=review.AREA_NAMES[area], bg=RAISED, fg=MUTED, font=self.f_tiny).pack()
        if info["weakest"]:
            tk.Label(box, text="Work on %s. %s" % (review.AREA_NAMES[info["weakest"]].lower(),
                                                   review.TIPS[info["weakest"]]),
                     bg=CARD, fg=TEXT, font=self.f_small, anchor="w", justify="left",
                     wraplength=px(360)).pack(fill="x", pady=(px(8), 0))

    # ----- updates
    def check_updates(self, manual=False):
        try:
            release = updates.latest_release()
        except Exception:
            if manual:
                self.ui(lambda: self.flash_status("Couldn't reach GitHub to check for updates."))
            return
        if updates.newer_than_current(release):
            self.release = release
            self.ui(self.show_banner)
        elif manual:
            self.ui(lambda: self.flash_status("You're on the latest version (%s)." % lol_coach.__version__))

    def manual_update_check(self):
        threading.Thread(target=lambda: self.check_updates(manual=True), daemon=True).start()

    def show_banner(self):
        tk, px = self.tk, self.px
        if self.downloading:
            return  # never rebuild the banner (and its button) mid-download
        if self.banner_inner is not None:
            self.banner_inner.destroy()
        self.banner.pack(fill="x", padx=px(18), pady=(0, px(12)), after=self.header)
        inner = self.banner_inner = tk.Frame(self.banner, bg=RAISED, highlightbackground=GOLD, highlightthickness=1,
                                             padx=px(14), pady=px(10))
        inner.pack(fill="x")
        self.banner_text = tk.Label(inner, text="Macro Goblin %s is out." % self.release["version"], bg=RAISED,
                                    fg=GOLD_HI, font=self.f_bold)
        self.banner_text.pack(side="left")
        self.btn_update = Button(inner, "Update now" if self.can_self_update() else "See what's new", self.run_update,
                                 px, self.f_small, kind="primary", bg=RAISED)
        self.btn_update.canvas.pack(side="right")
        self.fit_height()

    def can_self_update(self):
        """Only the installed app updates itself. Source checkouts and the portable zip open the release page."""
        installed = os.path.exists(os.path.join(os.path.dirname(sys.executable), "unins000.exe"))
        return lol_coach.FROZEN and installed and bool(self.release and self.release.get("installer"))

    def run_update(self):
        if not self.can_self_update():
            winplat.open_url(self.release["url"])
            return
        if self.downloading:
            return
        self.downloading = True
        self.btn_update.set_enabled(False)
        self.banner_text.configure(text="Downloading %s..." % self.release["version"])
        version = self.release["version"]

        def progress(fraction):
            self.ui(lambda: self.banner_text.configure(text="Downloading %s... %d%%" % (version, int(fraction * 100))))

        def work():
            try:
                path = updates.download_installer(self.release, progress=progress)
            except Exception as exc:
                message = "Update failed: %s" % exc

                def failed():
                    self.downloading = False
                    self.banner_text.configure(text=message)
                    self.btn_update.set_enabled(True)
                self.ui(failed)
                return
            self.ui(lambda: self.install_and_quit(path))

        threading.Thread(target=work, daemon=True).start()

    def install_and_quit(self, path):
        # The installer refuses to run while this app holds its single-instance lock, so it is
        # started from main() after the window has closed and the lock is released.
        self.banner_text.configure(text="Installing. Macro Goblin will reopen.")
        self.root.update_idletasks()
        self.pending_installer = path
        self.quit()

    # ----- errors / exit
    def on_callback_error(self, exc, value, tb):
        write_crash(exc, value, tb)
        try:
            self.flash_status("Something went wrong in the window. Details were saved to the logs folder.")
        except Exception:
            pass

    def request_close(self):
        """Closing mid-match stops your coach, so ask first. Otherwise close right away."""
        live = self.session is not None and not getattr(self, "demo_mode", False) and self.bus.snapshot().get("in_game")
        if live:
            from tkinter import messagebox
            if not messagebox.askyesno(TITLE, "You're in a match. Closing Macro Goblin stops the coach and the "
                                              "overlay.\n\nClose anyway?", icon="warning", parent=self.root):
                return
        self.quit()

    def quit(self):
        if self.closing:
            return
        self.closing = True
        try:
            self.show_overlay(False)
            self.stop_session(wait=True)
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def write_crash(exc_type, value, tb):
    try:
        folder = lol_coach.data_path("logs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("crash-%Y%m%d-%H%M%S.txt"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Macro Goblin %s\n" % lol_coach.__version__)
            handle.write("".join(traceback.format_exception(exc_type, value, tb)))
        return path
    except Exception:
        return None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Macro Goblin launcher")
    parser.add_argument("--minimized", action="store_true", help="start minimized (used by Start with Windows)")
    parser.add_argument("--demo", action="store_true", help="start with the demo match playing")
    parser.add_argument("--no-update-check", action="store_true")
    parser.add_argument("--version", action="version", version="Macro Goblin %s" % lol_coach.__version__)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not winplat.single_instance():
        winplat.focus_existing(TITLE)
        return 0
    sys.excepthook = lambda t, v, tb: (write_crash(t, v, tb), sys.__excepthook__(t, v, tb))
    threading.excepthook = lambda a: write_crash(a.exc_type, a.exc_value, a.exc_traceback)
    try:
        app = LauncherApp(args)
    except Exception:
        path = write_crash(*sys.exc_info())
        try:
            import tkinter.messagebox as box
            box.showerror(TITLE, "Macro Goblin could not start.\n\nDetails: %s" % (path or "unavailable"))
        except Exception:
            pass
        return 1
    app.run()
    if app.pending_installer:
        winplat.release_single_instance()
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")  # the relaunched app starts clean
        # /TASKS= keeps the person's own choices: no desktop icon or autostart re-added on update.
        subprocess.Popen([app.pending_installer, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS="],
                         close_fds=True, env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
