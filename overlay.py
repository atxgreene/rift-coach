"""Click-through overlay for Rift Coach.

Separate OS window. No DirectX hook, no injection, no keyboard hook, no memory read.
Mouse clicks pass through via WS_EX_TRANSPARENT. Show/hide is RegisterHotKey.
League must be Borderless. Exclusive fullscreen will cover this window.
"""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

import lol_coach

ROOT = lol_coach.ROOT
CONFIG = lol_coach.CONFIG

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
MOD_SHIFT = 0x0004
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_O = 0x4F
HOTKEY_ID = 0x4F10

CARD = "#10141c"
BRASS = "#d4b483"
TEXT = "#f4f1ea"
MUTED = "#8d93a0"
UP = "#8fbf9f"
SOON = "#e2b15a"
DOWN = "#d37b7b"
TRACK = "#1c2230"

user32 = ctypes.windll.user32


def screen_key():
    height = user32.GetSystemMetrics(1) if sys.platform.startswith("win") else 1080
    return "1440p" if height >= 1400 else "1080p"


def layout_path():
    return os.path.join(ROOT, "overlay_layout.json")


def load_layout():
    key = screen_key()
    base = dict(CONFIG["overlay"]["layouts"][key])
    path = layout_path()
    if os.path.exists(path):
        try:
            saved = json.load(open(path, encoding="utf-8")).get(key, {})
            for field in ("x", "y"):
                if field in saved:
                    base[field] = saved[field]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    base["key"] = key
    return base


def save_layout(key, x, y):
    path = layout_path()
    data = {}
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
    data.setdefault(key, {})
    data[key]["x"] = int(x)
    data[key]["y"] = int(y)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def top_hwnd(widget):
    child = widget.winfo_id()
    parent = user32.GetParent(child)
    return parent or child


def apply_exstyle(hwnd, click_through):
    flags = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    if click_through:
        flags |= WS_EX_TRANSPARENT
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | flags)
    user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )
    return user32.GetWindowLongW(hwnd, GWL_EXSTYLE)


def timer_style(remain):
    if remain is None:
        return "--", MUTED
    if remain <= 0:
        return "UP", UP
    if remain <= 60:
        return lol_coach.fmt_time(remain), SOON
    return lol_coach.fmt_time(remain), TEXT


def run(bus, stop, edit=False):
    import tkinter as tk
    from tkinter import font as tkfont

    layout = load_layout()
    scale = float(layout.get("scale", 1.0))
    width = int(layout["w"] * scale)
    height = int(560 * scale)
    fade = CONFIG["overlay"]["callout_fade_seconds"]

    root = tk.Tk()
    root.title("Rift Coach")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("%dx%d+%d+%d" % (width, height, layout["x"], layout["y"]))
    root.configure(bg="magenta")
    if not edit:
        try:
            root.attributes("-transparentcolor", "magenta")
        except tk.TclError:
            pass
    else:
        try:
            root.attributes("-alpha", layout.get("opacity", 0.94))
        except tk.TclError:
            pass

    family = "Segoe UI"
    title_font = tkfont.Font(family=family, size=max(8, int(9 * scale)), weight="bold")
    body_font = tkfont.Font(family=family, size=max(8, int(10 * scale)))
    mono_font = tkfont.Font(family="Consolas", size=max(9, int(12 * scale)))
    small_font = tkfont.Font(family=family, size=max(8, int(9 * scale)))

    shell = tk.Frame(root, bg=CARD)
    shell.pack(fill="both", expand=True)
    tk.Frame(shell, bg=BRASS, width=3).pack(side="left", fill="y")
    panel = tk.Frame(shell, bg=CARD, padx=10, pady=10)
    panel.pack(side="left", fill="both", expand=True)

    header = tk.Label(
        panel,
        text="RIFT" + ("  EDIT" if edit else ""),
        bg=CARD, fg=BRASS, font=title_font, anchor="w",
    )
    header.pack(fill="x")
    clock = tk.Label(panel, text="READY", bg=CARD, fg=TEXT, font=mono_font, anchor="w")
    clock.pack(fill="x")
    who = tk.Label(panel, text="Queue up", bg=CARD, fg=MUTED, font=body_font, anchor="w")
    who.pack(fill="x", pady=(0, 4))
    shop_label = tk.Label(
        panel, text="", bg=CARD, fg=BRASS, font=small_font, anchor="w",
        wraplength=width - 36, justify="left",
    )
    shop_label.pack(fill="x", pady=(0, 4))

    timer_labels = {}
    name_labels = {}
    for key, title in (("dragon", "Dragon"), ("grubs", "Grubs"), ("herald", "Herald"), ("baron", "Baron")):
        row = tk.Frame(panel, bg=CARD)
        row.pack(fill="x", pady=1)
        name = tk.Label(row, text=title, bg=CARD, fg=MUTED, font=body_font, width=8, anchor="w")
        name.pack(side="left")
        lbl = tk.Label(row, text="--", bg=CARD, fg=MUTED, font=mono_font, anchor="e")
        lbl.pack(side="right")
        timer_labels[key] = lbl
        name_labels[key] = name

    tk.Frame(panel, bg="#242a36", height=1).pack(fill="x", pady=8)
    callout_labels = []
    for _ in range(3):
        lbl = tk.Label(
            panel, text="", bg=CARD, fg=TEXT, font=small_font, anchor="w",
            wraplength=width - 36, justify="left",
        )
        lbl.pack(fill="x")
        callout_labels.append(lbl)

    gold_caption = tk.Label(panel, text="", bg=CARD, fg=MUTED, font=small_font, anchor="w")
    gold_caption.pack(fill="x", pady=(8, 0))
    gold_canvas = tk.Canvas(panel, width=width - 36, height=int(8 * scale), bg=CARD, highlightthickness=0)
    gold_canvas.pack(fill="x")
    cs_label = tk.Label(panel, text="", bg=CARD, fg=TEXT, font=small_font, anchor="w")
    cs_label.pack(fill="x", pady=(6, 0))
    spike_label = tk.Label(
        panel, text="", bg=CARD, fg=SOON, font=small_font, anchor="w",
        wraplength=width - 36, justify="left",
    )
    spike_label.pack(fill="x", pady=(4, 0))

    hidden = {"value": False}
    drag = {"x": 0, "y": 0}
    ticks = {"n": 0}

    def hide_show():
        hidden["value"] = not hidden["value"]
        if hidden["value"]:
            root.withdraw()
        else:
            root.deiconify()
            root.attributes("-topmost", True)
            root.after(50, apply_style)

    def apply_style():
        if not sys.platform.startswith("win"):
            return 0
        root.update_idletasks()
        return apply_exstyle(top_hwnd(root), click_through=not edit and not hidden["value"])

    def poll_hotkey():
        if sys.platform.startswith("win"):
            msg = wintypes.MSG()
            while user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                hide_show()
        if stop.is_set():
            root.destroy()
            return
        root.after(50, poll_hotkey)

    def refresh():
        state = bus.snapshot()
        in_game = bool(state.get("in_game"))
        ticks["n"] += 1
        clock.configure(text=state.get("clock") or "READY", fg=TEXT)
        if in_game:
            champ = state.get("champion") or "Live"
            pos = state.get("position") or ""
            kda = state.get("kda") or ""
            level = state.get("level")
            level_bit = "  lvl %s" % level if level else ""
            who.configure(text="%s  %s  %s%s" % (champ, pos, kda, level_bit), fg=TEXT)
        else:
            who.configure(text=state.get("hint") or "Queue up. Borderless.", fg=MUTED)
        now_t = state.get("t")
        spawns = state.get("spawns") or {}
        labels = {
            "dragon": "Elder" if state.get("elder") else "Dragon",
            "grubs": "Grubs",
            "herald": "Herald",
            "baron": "Baron",
        }
        for key, lbl in timer_labels.items():
            name_labels[key].configure(text=labels[key])
            remain = None
            if in_game and key in spawns and now_t is not None:
                remain = spawns[key] - now_t
            text, color = timer_style(remain if in_game else None)
            lbl.configure(text=text, fg=color)
        visible = []
        wall = time.time()
        for row in state.get("callouts") or []:
            if len(row) < 3 or wall - row[2] > fade:
                continue
            visible.append(row[1])
        for idx, lbl in enumerate(callout_labels):
            lbl.configure(text=visible[idx] if idx < len(visible) else "")
        gold_canvas.delete("all")
        if not in_game:
            gold_caption.configure(text="")
            cs_label.configure(text="")
            spike_label.configure(text="")
            shop_label.configure(text="")
        else:
            diff = state.get("gold_diff", 0) or 0
            prev = state.get("prev_gold_diff", diff) or 0
            arrow = "^" if diff > prev + 200 else ("v" if diff < prev - 200 else "-")
            side = "+" if diff >= 0 else ""
            gold_caption.configure(text="Gold %s%.1fk %s" % (side, diff / 1000.0, arrow))
            bar_w = max(10, width - 36)
            mid = bar_w / 2
            gold_canvas.create_rectangle(0, 2, bar_w, int(8 * scale), fill=TRACK, outline="")
            span = max(-1.0, min(1.0, diff / 5000.0)) * (bar_w / 2)
            color = UP if diff >= 0 else DOWN
            if span >= 0:
                gold_canvas.create_rectangle(mid, 2, mid + span, int(8 * scale), fill=color, outline="")
            else:
                gold_canvas.create_rectangle(mid + span, 2, mid, int(8 * scale), fill=color, outline="")
            pos = state.get("position")
            if pos == "UTILITY":
                cs_label.configure(text="")
            else:
                rate = state.get("cs_rate", 0) or 0
                target = state.get("cs_target", 8) or 8
                if rate >= target - 0.3:
                    color = UP
                elif rate >= target - 1.5:
                    color = SOON
                else:
                    color = DOWN
                cs_label.configure(text="CS %.1f / %g" % (rate, target), fg=color)
            spike_label.configure(text="\n".join((state.get("spikes") or [])[-2:]))
            shop_label.configure(text="\n".join(state.get("shop") or []))
        if ticks["n"] % 20 == 0 and not hidden["value"]:
            root.attributes("-topmost", True)
            apply_style()
        root.after(100, refresh)

    if edit:
        def start_drag(event):
            drag["x"] = event.x_root - root.winfo_x()
            drag["y"] = event.y_root - root.winfo_y()

        def on_drag(event):
            root.geometry("+%d+%d" % (event.x_root - drag["x"], event.y_root - drag["y"]))

        def end_drag(_event):
            save_layout(layout["key"], root.winfo_x(), root.winfo_y())

        def bind_drag(widget):
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<ButtonRelease-1>", end_drag)
            for child in widget.winfo_children():
                bind_drag(child)

        bind_drag(shell)

    hotkey_ok = None
    if sys.platform.startswith("win"):
        hotkey_ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_O)
        if not hotkey_ok:
            print("Overlay hotkey Ctrl+Shift+O is already taken. Overlay still shows.", flush=True)

    def on_close():
        if sys.platform.startswith("win"):
            user32.UnregisterHotKey(None, HOTKEY_ID)
        stop.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(80, apply_style)
    root.after(100, refresh)
    root.after(50, poll_hotkey)
    try:
        root.mainloop()
    finally:
        if sys.platform.startswith("win"):
            user32.UnregisterHotKey(None, HOTKEY_ID)
        stop.set()
        del hotkey_ok
