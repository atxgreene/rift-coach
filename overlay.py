"""Click-through overlay for Rift Coach.

This is a separate OS window. It does not hook DirectX, inject into League,
install a keyboard hook, or read game memory. Mouse clicks pass through via
WS_EX_TRANSPARENT. The show/hide key is RegisterHotKey, not a low-level hook.

League must be in Borderless windowed mode. Exclusive fullscreen will cover this window.
"""

import ctypes
import json
import os
import sys
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


def run(bus, stop, edit=False):
    import tkinter as tk
    from tkinter import font as tkfont

    layout = load_layout()
    scale = float(layout.get("scale", 1.0))
    width = int(layout["w"] * scale)
    height = int(470 * scale)
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
    mono_font = tkfont.Font(family="Consolas", size=max(8, int(11 * scale)))

    panel = tk.Frame(root, bg="#141820", padx=8, pady=8)
    panel.pack(fill="both", expand=True)

    header = tk.Label(panel, text="RIFT COACH" + ("  EDIT" if edit else ""), bg="#141820", fg="#8b909a", font=title_font, anchor="w")
    header.pack(fill="x")
    clock = tk.Label(panel, text="--:--", bg="#141820", fg="#e7e5e4", font=mono_font, anchor="w")
    clock.pack(fill="x")

    timer_labels = {}
    name_labels = {}
    for key, title in (("dragon", "Dragon"), ("grubs", "Grubs"), ("herald", "Herald"), ("baron", "Baron")):
        row = tk.Frame(panel, bg="#141820")
        row.pack(fill="x", pady=1)
        name = tk.Label(row, text=title, bg="#141820", fg="#8b909a", font=body_font, width=8, anchor="w")
        name.pack(side="left")
        lbl = tk.Label(row, text="--", bg="#141820", fg="#e7e5e4", font=mono_font, anchor="e")
        lbl.pack(side="right")
        timer_labels[key] = lbl
        name_labels[key] = name

    tk.Frame(panel, bg="#2a3140", height=1).pack(fill="x", pady=6)
    callout_labels = []
    for _ in range(3):
        lbl = tk.Label(panel, text="", bg="#141820", fg="#e7e5e4", font=body_font, anchor="w", wraplength=width - 24, justify="left")
        lbl.pack(fill="x")
        callout_labels.append(lbl)

    tk.Frame(panel, bg="#2a3140", height=1).pack(fill="x", pady=6)
    gold_caption = tk.Label(panel, text="Item gold", bg="#141820", fg="#8b909a", font=body_font, anchor="w")
    gold_caption.pack(fill="x")
    gold_canvas = tk.Canvas(panel, width=width - 24, height=int(12 * scale), bg="#141820", highlightthickness=0)
    gold_canvas.pack(fill="x")
    cs_label = tk.Label(panel, text="", bg="#141820", fg="#e7e5e4", font=body_font, anchor="w")
    cs_label.pack(fill="x", pady=(6, 0))
    spike_label = tk.Label(panel, text="", bg="#141820", fg="#f0b45a", font=body_font, anchor="w", wraplength=width - 24, justify="left")
    spike_label.pack(fill="x", pady=(4, 0))

    hidden = {"value": False}
    drag = {"x": 0, "y": 0}

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
        now_t = state.get("t")
        clock.configure(text=state.get("clock", "waiting") if state else "waiting")
        spawns = state.get("spawns") or {}
        labels = {"dragon": "Elder" if state.get("elder") else "Dragon", "grubs": "Grubs", "herald": "Herald", "baron": "Baron"}
        for key, lbl in timer_labels.items():
            name_labels[key].configure(text=labels[key])
            if key not in spawns or now_t is None:
                lbl.configure(text="--", fg="#5c6370")
                continue
            remain = spawns[key] - now_t
            if remain <= 0:
                lbl.configure(text="UP", fg="#7dcea0")
            elif remain <= 60:
                lbl.configure(text=lol_coach.fmt_time(remain), fg="#f0b45a")
            else:
                lbl.configure(text=lol_coach.fmt_time(remain), fg="#e7e5e4")
        callouts = state.get("callouts") or []
        visible = []
        wall = __import__("time").time()
        for row in callouts:
            if len(row) < 3 or wall - row[2] > fade:
                continue
            visible.append(row[1])
        for idx, lbl in enumerate(callout_labels):
            lbl.configure(text=visible[idx] if idx < len(visible) else "")
        diff = state.get("gold_diff", 0) or 0
        prev = state.get("prev_gold_diff", diff) or 0
        arrow = "^" if diff > prev + 200 else ("v" if diff < prev - 200 else "-")
        side = "+" if diff >= 0 else "-"
        gold_caption.configure(text="Item gold %s%.1fk %s" % (side, abs(diff) / 1000.0, arrow))
        gold_canvas.delete("all")
        bar_w = max(10, width - 24)
        mid = bar_w / 2
        gold_canvas.create_rectangle(0, 2, bar_w, int(10 * scale), fill="#222733", outline="")
        span = max(-1.0, min(1.0, diff / 5000.0)) * (bar_w / 2)
        color = "#7dcea0" if diff >= 0 else "#e07a7a"
        if span >= 0:
            gold_canvas.create_rectangle(mid, 2, mid + span, int(10 * scale), fill=color, outline="")
        else:
            gold_canvas.create_rectangle(mid + span, 2, mid, int(10 * scale), fill=color, outline="")
        pos = state.get("position")
        if not state or pos == "UTILITY":
            cs_label.configure(text="" if pos == "UTILITY" else "CS --")
        else:
            rate = state.get("cs_rate", 0) or 0
            target = state.get("cs_target", 8) or 8
            if rate >= target - 0.3:
                color = "#7dcea0"
            elif rate >= target - 1.5:
                color = "#f0b45a"
            else:
                color = "#e07a7a"
            cs_label.configure(text="CS %.1f / %g" % (rate, target), fg=color)
        spikes = state.get("spikes") or []
        spike_label.configure(text="\n".join(spikes[-2:]))
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

        bind_drag(panel)

    hotkey_ref = None
    if sys.platform.startswith("win"):
        ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_O)
        if not ok:
            print("Overlay hotkey Ctrl+Shift+O was already taken. Overlay still shows.", flush=True)
        hotkey_ref = ok

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
        del hotkey_ref
