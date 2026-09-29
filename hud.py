"""Compact in-game HUD: a slim strip that sits in empty screen space next to League's own HUD.

Default spot is just above the minimap, on whichever side League draws it, sized from the
minimap scale in League's own settings file. The file is only read, never written, and the
strip is a separate click-through window like the full overlay card: no hooks, no injection.

Rows:
  timers   DRG 1:24   BAR 11:09   GRB UP   HER 6:09          +0.4k
  next     NEXT  Yun Tal Wildarrows  ·  need 1775
  call     Dragon in 60 seconds.                    (fades after a few seconds)
"""

import json
import os
import re
import string
import time

import lol_coach

CONFIG = lol_coach.CONFIG

# League client palette: near-black blue, dark gold edge, parchment text, hextech teal.
BG = "#010a13"
EDGE = "#785a28"
EDGE_HI = "#c8aa6e"
TEXT = "#f0e6d2"
MUTED = "#a09b8c"
GOLD = "#c8aa6e"
TEAL = "#0ac8b9"
SOON = "#f0b45a"
URGENT = "#e84057"
DIM = "#5b5a56"
TRANSPARENT = "#ff00fe"

HUD_DEFAULTS = {
    # Minimap edge length at 1080p for MinimapScale 0 and 1 (League's slider 0-100%).
    # Calibrated from screenshots; the strip sits `gap` px above it.
    "minimap_px_1080": (190, 420),
    "gap": 14,
    "edge_margin": 8,
    "width_1080": 356,
    "opacity": 0.92,
    "call_seconds": 7,
}


# ----- League settings (read-only) -------------------------------------------
def _league_config_dirs():
    dirs = []
    for drive in ["C"] + [d for d in string.ascii_uppercase if d not in "ABC"]:
        for base in ("Riot Games\\League of Legends", "Program Files\\Riot Games\\League of Legends",
                     "Games\\Riot Games\\League of Legends", "Games\\League of Legends"):
            dirs.append("%s:\\%s\\Config" % (drive, base))
    return dirs


def _walk_settings(node, found):
    """PersistedSettings.json nests {"name": X, "value": Y} pairs inside files/sections."""
    if isinstance(node, dict):
        name, value = node.get("name"), node.get("value")
        if isinstance(name, str) and value is not None and not isinstance(value, (dict, list)):
            found.setdefault(name, value)
        for child in node.values():
            _walk_settings(child, found)
    elif isinstance(node, list):
        for child in node:
            _walk_settings(child, found)


def _read_ini(path, found):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = re.match(r"\s*([A-Za-z]\w*)\s*=\s*(.*?)\s*$", line)
            if match:
                found.setdefault(match.group(1), match.group(2))


def league_settings(config_dirs=None):
    """{'minimap_scale': float 0..1 or None, 'minimap_left': bool, 'source': path or ''}."""
    found, source = {}, ""
    override = os.environ.get("MACROGOBLIN_LEAGUE_CONFIG")
    dirs = [override] if override else (config_dirs if config_dirs is not None else
                                        (_league_config_dirs() if lol_coach.sys.platform.startswith("win") else []))
    for folder in dirs:
        if not folder or not os.path.isdir(folder):
            continue
        persisted = os.path.join(folder, "PersistedSettings.json")
        try:
            if os.path.isfile(persisted):
                with open(persisted, encoding="utf-8", errors="replace") as handle:
                    _walk_settings(json.load(handle), found)
                source = persisted
            game_cfg = os.path.join(folder, "game.cfg")
            if os.path.isfile(game_cfg):
                _read_ini(game_cfg, found)
                source = source or game_cfg
        except (OSError, ValueError):
            continue
        if found:
            break
    scale = None
    try:
        if "MinimapScale" in found:
            scale = max(0.0, min(1.0, float(found["MinimapScale"])))
    except (TypeError, ValueError):
        scale = None
    flip = str(found.get("FlipMiniMap", "0")).strip().lower() in ("1", "true")
    return {"minimap_scale": scale, "minimap_left": flip, "source": source}


def minimap_px(screen_h, scale):
    """Estimated minimap edge in screen pixels. Unknown scale -> the largest, so we never overlap it."""
    small, large = HUD_DEFAULTS["minimap_px_1080"]
    frac = 1.0 if scale is None else scale
    return int((small + (large - small) * frac) * screen_h / 1080.0)


def default_spot(screen_w, screen_h, width, height, league=None):
    """Top-left corner for the strip: just above the minimap, flush with its outer edge."""
    league = league or {}
    margin = int(HUD_DEFAULTS["edge_margin"] * screen_h / 1080.0)
    gap = int(HUD_DEFAULTS["gap"] * screen_h / 1080.0)
    bottom = screen_h - minimap_px(screen_h, league.get("minimap_scale")) - gap
    x = margin if league.get("minimap_left") else screen_w - width - margin
    return max(0, x), max(0, bottom - height)


# ----- text helpers ----------------------------------------------------------
LABELS = (("dragon", "DRG"), ("baron", "BAR"), ("grubs", "GRB"), ("herald", "HER"))


def timer_cells(state):
    """[(label, text, color)] for the four pits, plus which one is next."""
    now = state.get("t")
    spawns = state.get("spawns") or {}
    cells, soonest = [], None
    for key, label in LABELS:
        if key == "dragon" and state.get("elder"):
            label = "ELD"
        if now is None or key not in spawns:
            cells.append((label, "--", DIM))
            continue
        remain = spawns[key] - now
        if remain <= 0:
            text, color = "UP", TEAL
        else:
            text = lol_coach.fmt_time(remain)
            color = URGENT if remain <= 30 else (SOON if remain <= 60 else TEXT)
        if soonest is None or remain < soonest[1]:
            soonest = (label, remain)
        cells.append((label, text, color))
    return cells, (soonest[0] if soonest else None)


def next_buy(state):
    for raw in state.get("shop") or []:
        line = str(raw)
        if line.startswith("NEXT "):
            fields = [f.strip() for f in line[5:].split("  ") if f.strip()]
            if not fields:
                return ""
            extra = [f for f in fields[1:] if f.startswith("need") or f == "BUY"]
            tail = ("buy now" if extra and extra[0] == "BUY" else extra[0]) if extra else ""
            return fields[0] + (("  \u00b7  " + tail) if tail else "")
    return ""


def latest_call(state, now=None, seconds=None):
    seconds = HUD_DEFAULTS["call_seconds"] if seconds is None else seconds
    now = time.time() if now is None else now
    for row in reversed(state.get("callouts") or []):
        if len(row) >= 3 and now - row[2] <= seconds:
            return row[1]
    return ""


def gold_chip(state):
    if not state.get("in_game") or state.get("gold_ok") is False:
        return "", MUTED
    diff = state.get("gold_diff", 0) or 0
    if abs(diff) < 250:
        return "even", MUTED
    return ("%+.1fk" % (diff / 1000.0)), (TEAL if diff > 0 else URGENT)


def clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "\u2026"


# ----- window -----------------------------------------------------------------
class CompactHud:
    """A Toplevel owned by the overlay. The overlay decides visibility and click-through."""

    def __init__(self, master, layout_key, saved=None, league=None):
        import tkinter as tk
        from tkinter import font as tkfont

        self.tk = tk
        self.root = tk.Toplevel(master)
        self.root.withdraw()
        self.root.title("Macro Goblin HUD")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.layout_key = layout_key
        self.league = league if league is not None else league_settings()
        self.saved = saved or {}
        self.visible = False

        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.screen = (screen_w, screen_h)
        dpi = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.unit = max(0.75, screen_h / 1080.0) / dpi  # font points scale with DPI already
        self.width = int(HUD_DEFAULTS["width_1080"] * screen_h / 1080.0)

        pt = lambda n: max(7, int(round(n * self.unit)))  # noqa: E731
        family = "Segoe UI"
        self.f_label = tkfont.Font(family=family, size=pt(7), weight="bold")
        self.f_time = tkfont.Font(family="Consolas", size=pt(10), weight="bold")
        self.f_next = tkfont.Font(family=family, size=pt(9), weight="bold")
        self.f_call = tkfont.Font(family=family, size=pt(9))
        self.chars = max(30, int(self.width / max(6, self.f_call.measure("n"))))

        try:
            self.root.attributes("-alpha", HUD_DEFAULTS["opacity"])
        except tk.TclError:
            pass
        self.root.configure(bg=EDGE)
        # Two-tone edge like League's frames: dark gold outside, a thin bright line on top.
        self.shell = tk.Frame(self.root, bg=BG, highlightbackground=EDGE, highlightthickness=1)
        self.shell.pack(fill="both", expand=True)
        tk.Frame(self.shell, bg=EDGE_HI, height=1).pack(fill="x")
        body = tk.Frame(self.shell, bg=BG, padx=int(8 * self.unit * dpi), pady=int(5 * self.unit * dpi))
        body.pack(fill="both", expand=True)

        timers = tk.Frame(body, bg=BG)
        timers.pack(fill="x")
        self.cells = []
        for idx in range(4):
            cell = tk.Frame(timers, bg=BG)
            cell.pack(side="left", padx=(0, int(9 * self.unit * dpi)))
            name = tk.Label(cell, text="", bg=BG, fg=MUTED, font=self.f_label)
            name.pack(side="left", padx=(0, 3))
            value = tk.Label(cell, text="--", bg=BG, fg=DIM, font=self.f_time)
            value.pack(side="left")
            self.cells.append((name, value))
        self.gold = tk.Label(timers, text="", bg=BG, fg=MUTED, font=self.f_label)
        self.gold.pack(side="right")

        self.rule = tk.Frame(body, bg="#1e2328", height=1)
        self.rule.pack(fill="x", pady=(4, 3))
        self.next = tk.Label(body, text="", bg=BG, fg=GOLD, font=self.f_next, anchor="w")
        self.next.pack(fill="x")
        self.call = tk.Label(body, text="", bg=BG, fg=TEXT, font=self.f_call, anchor="w", justify="left",
                             wraplength=self.width - int(20 * self.unit * dpi))
        self.call_shown = False
        self.last_size = None
        self.anchor_bottom = None  # the strip grows upward from here, so it never slides onto the minimap
        self.place_initial()

    # placement
    def place_initial(self):
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        x, y = self.saved.get("x"), self.saved.get("y")
        screen_w, screen_h = self.screen
        if x is None or y is None or not (-self.width + 40 <= int(x) <= screen_w - 40 and 0 <= int(y) <= screen_h - 20):
            x, y = default_spot(screen_w, screen_h, self.width, height, self.league)
        self.anchor_bottom = int(y) + height
        self.x = int(x)
        self.apply_geometry(height)

    def apply_geometry(self, height):
        y = max(0, self.anchor_bottom - height)
        size = (self.width, height, self.x, y)
        if size != self.last_size:
            self.root.geometry("%dx%d+%d+%d" % size)
            self.last_size = size

    def moved_to(self, x, y):
        self.x = int(x)
        self.anchor_bottom = int(y) + self.root.winfo_height()
        self.last_size = None

    def spot(self):
        return {"x": self.x, "y": self.anchor_bottom - self.root.winfo_height()}

    # drawing
    def draw(self, state, placeholder=False):
        in_game = bool(state.get("in_game"))
        cells, soonest = timer_cells(state if in_game else {})
        for (name, value), (label, text, color) in zip(self.cells, cells):
            name.configure(text=label, fg=GOLD if label == soonest else MUTED)
            value.configure(text=text, fg=color)
        gold, gold_color = gold_chip(state)
        self.gold.configure(text=("GOLD " + gold) if gold else "", fg=gold_color)
        buy = next_buy(state) if in_game else ""
        if buy:
            self.next.configure(text=clip("NEXT  " + buy, self.chars), fg=GOLD)
        elif placeholder:
            self.next.configure(text="Macro Goblin HUD  \u00b7  drag me, Ctrl+Shift+M to lock", fg=MUTED)
        else:
            self.next.configure(text="", fg=GOLD)
        call = latest_call(state) if in_game else ""
        if call and not self.call_shown:
            self.call.pack(fill="x", pady=(2, 0))
            self.call_shown = True
        elif not call and self.call_shown:
            self.call.pack_forget()
            self.call_shown = False
        self.call.configure(text=clip(call, self.chars * 2))
        self.root.update_idletasks()
        self.apply_geometry(self.root.winfo_reqheight())

    def show(self):
        if not self.visible:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.visible = True

    def hide(self):
        if self.visible:
            self.root.withdraw()
            self.visible = False
