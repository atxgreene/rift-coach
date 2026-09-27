"""Click-through overlay for Rift Coach.

Separate OS window. No DirectX hook, no injection, no keyboard hook, no memory read.
Mouse clicks pass through via WS_EX_TRANSPARENT during play. Show/hide and move-mode
use RegisterHotKey, not a low-level keyboard hook.
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
VK_M = 0x4D
HOTKEY_HIDE_ID = 0x4F10
HOTKEY_MOVE_ID = 0x4D10
# Back-compat for the smoke test.
HOTKEY_ID = HOTKEY_HIDE_ID

# Riot-inspired palette: dark slate panels, thin gold accents, restrained status colors.
TRANSPARENT = "magenta"
BG = "#05080d"
PANEL = "#0b1420"
PANEL_2 = "#101b2b"
PANEL_3 = "#07101a"
GOLD = "#c8aa6e"
GOLD_BRIGHT = "#f0d58c"
TEXT = "#f0e6d2"
MUTED = "#8a93a5"
BLUE = "#3fb7d8"
UP = "#7bd88f"
SOON = "#f0b45a"
DOWN = "#d86b6b"
TRACK = "#1e2a3d"
WARN_BG = "#24140c"

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
            for field in ("x", "y", "w", "scale", "opacity"):
                if field in saved:
                    base[field] = saved[field]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    base["key"] = key
    return base


def save_layout(key, x, y, width=None, scale=None):
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
    if width is not None:
        data[key]["w"] = int(width)
    if scale is not None:
        data[key]["scale"] = float(scale)
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
    # Clear/restore transparent each time so move mode can grab the card.
    style = (style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_TRANSPARENT
    if click_through:
        style |= WS_EX_TRANSPARENT
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
    if remain <= 30:
        return lol_coach.fmt_time(remain), DOWN
    if remain <= 60:
        return lol_coach.fmt_time(remain), SOON
    return lol_coach.fmt_time(remain), TEXT


def gold_text(diff, prev):
    arrow = "↑" if diff > prev + 200 else ("↓" if diff < prev - 200 else "→")
    side = "+" if diff >= 0 else ""
    return "%s%.1fk %s" % (side, diff / 1000.0, arrow)


def next_objective(state):
    if not state.get("in_game"):
        return "QUEUE", "Waiting", None, MUTED
    now = state.get("t")
    spawns = state.get("spawns") or {}
    names = {
        "dragon": "ELDER" if state.get("elder") else "DRAGON",
        "baron": "BARON",
        "herald": "HERALD",
        "grubs": "GRUBS",
    }
    if now is None or not spawns:
        return "MAP", "No tracked objective", None, MUTED
    best = None
    for key, at in spawns.items():
        remain = at - now
        row = (max(remain, -9999), key, remain)
        if best is None or row[0] < best[0]:
            best = row
    _rank, key, remain = best
    text, color = timer_style(remain)
    return names.get(key, key.upper()), text, remain, color


def split_shop(lines):
    alert = ""
    buy = []
    later = []
    for raw in lines or []:
        line = str(raw).strip()
        if not line:
            continue
        if line.startswith("BUILD"):
            alert = line.replace("BUILD", "PLAN", 1).strip()
        elif line.startswith(("BUY", "THEN")):
            buy.append(line)
        elif line.startswith(("HAVE", "LATER")):
            later.append(line)
        else:
            # Pattern guidance / warning lines from the coach.
            if not alert:
                alert = line
            else:
                later.append(line)
    return alert, buy[:3], later[:3]


def pack_section(parent, title, scale, tk, tkfont):
    frame = tk.Frame(parent, bg=PANEL, highlightbackground="#1d314c", highlightthickness=1)
    frame.pack(fill="x", pady=(0, int(7 * scale)))
    tk.Label(
        frame, text=title, bg=PANEL_3, fg=GOLD, font=tkfont.Font(family="Segoe UI", size=max(7, int(8 * scale)), weight="bold"),
        anchor="w", padx=7, pady=2,
    ).pack(fill="x")
    body = tk.Frame(frame, bg=PANEL, padx=7, pady=5)
    body.pack(fill="x")
    return body


def run(bus, stop, edit=False):
    import tkinter as tk
    from tkinter import font as tkfont

    layout = load_layout()
    scale = float(layout.get("scale", 1.0))
    width = int(layout["w"] * scale)
    height = int(604 * scale)
    fade = CONFIG["overlay"].get("callout_fade_seconds", 12)

    root = tk.Tk()
    root.title("Rift Coach")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("%dx%d+%d+%d" % (width, height, layout["x"], layout["y"]))
    root.configure(bg=TRANSPARENT)
    if not edit:
        try:
            root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
    else:
        try:
            root.attributes("-alpha", layout.get("opacity", 0.94))
        except tk.TclError:
            pass

    family = "Segoe UI"
    tiny_font = tkfont.Font(family=family, size=max(7, int(8 * scale)))
    title_font = tkfont.Font(family=family, size=max(8, int(9 * scale)), weight="bold")
    body_font = tkfont.Font(family=family, size=max(8, int(10 * scale)))
    bold_font = tkfont.Font(family=family, size=max(8, int(10 * scale)), weight="bold")
    mono_font = tkfont.Font(family="Consolas", size=max(10, int(14 * scale)), weight="bold")
    small_mono = tkfont.Font(family="Consolas", size=max(8, int(10 * scale)))

    shell = tk.Frame(root, bg=BG, highlightbackground=GOLD, highlightthickness=1)
    shell.pack(fill="both", expand=True)
    tk.Frame(shell, bg=GOLD, height=2).pack(fill="x")
    panel = tk.Frame(shell, bg=BG, padx=9, pady=8)
    panel.pack(fill="both", expand=True)

    move_mode = {"value": bool(edit)}
    hidden = {"value": False}
    drag = {"x": 0, "y": 0}
    ticks = {"n": 0}

    header = tk.Frame(panel, bg=BG)
    header.pack(fill="x")
    tk.Label(header, text="RIFT COACH", bg=BG, fg=GOLD_BRIGHT, font=title_font, anchor="w").pack(side="left")
    mode_label = tk.Label(header, text="MOVE" if edit else "LIVE", bg=BG, fg=SOON if edit else BLUE, font=tiny_font, anchor="e")
    mode_label.pack(side="right")

    clock_row = tk.Frame(panel, bg=BG)
    clock_row.pack(fill="x", pady=(1, 5))
    clock = tk.Label(clock_row, text="READY", bg=BG, fg=TEXT, font=mono_font, anchor="w")
    clock.pack(side="left")
    hotkey_hint = tk.Label(clock_row, text="Ctrl+Shift+M move", bg=BG, fg=MUTED, font=tiny_font, anchor="e")
    hotkey_hint.pack(side="right")

    who = tk.Label(panel, text="Queue up. Borderless.", bg=BG, fg=MUTED, font=body_font, anchor="w")
    who.pack(fill="x", pady=(0, 7))

    alert_box = tk.Frame(panel, bg=WARN_BG, highlightbackground="#5c371e", highlightthickness=1)
    alert_box.pack(fill="x", pady=(0, 7))
    alert_title = tk.Label(alert_box, text="FOCUS", bg=WARN_BG, fg=GOLD, font=tiny_font, anchor="w", padx=7, pady=2)
    alert_title.pack(fill="x")
    alert_label = tk.Label(
        alert_box, text="Waiting for live game data", bg=WARN_BG, fg=TEXT, font=bold_font,
        anchor="w", justify="left", wraplength=width - 28, padx=7, pady=5,
    )
    alert_label.pack(fill="x")

    obj_body = pack_section(panel, "NEXT OBJECTIVE", scale, tk, tkfont)
    obj_top = tk.Frame(obj_body, bg=PANEL)
    obj_top.pack(fill="x")
    obj_name = tk.Label(obj_top, text="QUEUE", bg=PANEL, fg=GOLD_BRIGHT, font=bold_font, anchor="w")
    obj_name.pack(side="left")
    obj_time = tk.Label(obj_top, text="--", bg=PANEL, fg=MUTED, font=mono_font, anchor="e")
    obj_time.pack(side="right")
    timer_labels = {}
    name_labels = {}
    grid = tk.Frame(obj_body, bg=PANEL)
    grid.pack(fill="x", pady=(4, 0))
    for idx, (key, title) in enumerate((('dragon', 'DRG'), ('baron', 'BAR'), ('grubs', 'GRB'), ('herald', 'HER'))):
        cell = tk.Frame(grid, bg=PANEL_2, padx=5, pady=3)
        cell.grid(row=0, column=idx, padx=(0 if idx == 0 else 3, 0), sticky="ew")
        grid.columnconfigure(idx, weight=1)
        name = tk.Label(cell, text=title, bg=PANEL_2, fg=MUTED, font=tiny_font)
        name.pack()
        lbl = tk.Label(cell, text="--", bg=PANEL_2, fg=MUTED, font=small_mono)
        lbl.pack()
        timer_labels[key] = lbl
        name_labels[key] = name

    metrics_body = pack_section(panel, "LANE STATE", scale, tk, tkfont)
    metric_row = tk.Frame(metrics_body, bg=PANEL)
    metric_row.pack(fill="x")
    gold_label = tk.Label(metric_row, text="Gold --", bg=PANEL, fg=MUTED, font=body_font, anchor="w")
    gold_label.grid(row=0, column=0, sticky="w")
    cs_label = tk.Label(metric_row, text="CS --", bg=PANEL, fg=MUTED, font=body_font, anchor="e")
    cs_label.grid(row=0, column=1, sticky="e")
    metric_row.columnconfigure(0, weight=1)
    metric_row.columnconfigure(1, weight=1)
    gold_canvas = tk.Canvas(metrics_body, width=width - 36, height=int(9 * scale), bg=PANEL, highlightthickness=0)
    gold_canvas.pack(fill="x", pady=(5, 0))

    shop_body = pack_section(panel, "ITEM PLAN", scale, tk, tkfont)
    shop_next = tk.Label(shop_body, text="", bg=PANEL, fg=GOLD_BRIGHT, font=bold_font, anchor="w", justify="left", wraplength=width - 34)
    shop_next.pack(fill="x")
    shop_later = tk.Label(shop_body, text="", bg=PANEL, fg=MUTED, font=tiny_font, anchor="w", justify="left", wraplength=width - 34)
    shop_later.pack(fill="x", pady=(3, 0))

    calls_body = pack_section(panel, "RECENT CALLS", scale, tk, tkfont)
    callout_labels = []
    for _ in range(3):
        lbl = tk.Label(calls_body, text="", bg=PANEL, fg=TEXT, font=tiny_font, anchor="w", justify="left", wraplength=width - 34)
        lbl.pack(fill="x")
        callout_labels.append(lbl)

    footer = tk.Label(panel, text="Ctrl+Shift+O hide • Ctrl+Shift+M move/save", bg=BG, fg=MUTED, font=tiny_font, anchor="center")
    footer.pack(fill="x", side="bottom")

    def apply_style():
        if not sys.platform.startswith("win"):
            return 0
        root.update_idletasks()
        click = not move_mode["value"] and not hidden["value"]
        return apply_exstyle(top_hwnd(root), click_through=click)

    def set_move_mode(value):
        move_mode["value"] = bool(value)
        mode_label.configure(text="MOVE" if move_mode["value"] else "LIVE", fg=SOON if move_mode["value"] else BLUE)
        hotkey_hint.configure(text="Drag card; saved" if move_mode["value"] else "Ctrl+Shift+M move")
        apply_style()
        if not move_mode["value"]:
            save_layout(layout["key"], root.winfo_x(), root.winfo_y(), width=int(layout["w"]), scale=scale)

    def toggle_move_mode():
        if hidden["value"]:
            return
        set_move_mode(not move_mode["value"])

    def hide_show():
        hidden["value"] = not hidden["value"]
        if hidden["value"]:
            root.withdraw()
        else:
            root.deiconify()
            root.attributes("-topmost", True)
            root.after(50, apply_style)

    def poll_hotkey():
        if sys.platform.startswith("win"):
            msg = wintypes.MSG()
            while user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                hotkey_id = getattr(msg, "wParam", 0)
                if hotkey_id == HOTKEY_MOVE_ID:
                    toggle_move_mode()
                else:
                    hide_show()
        if stop.is_set():
            root.destroy()
            return
        root.after(50, poll_hotkey)

    def refresh():
        state = bus.snapshot()
        in_game = bool(state.get("in_game"))
        ticks["n"] += 1

        clock.configure(text=state.get("clock") or "READY", fg=TEXT if in_game else MUTED)
        if in_game:
            champ = state.get("champion") or "Live"
            pos = state.get("position") or ""
            kda = state.get("kda") or ""
            level = state.get("level")
            level_bit = "LVL %s" % level if level else ""
            who.configure(text=" • ".join(x for x in (champ, pos, kda, level_bit) if x), fg=TEXT)
        else:
            who.configure(text=state.get("hint") or "Queue up. Borderless.", fg=MUTED)

        shop_alert, buy_lines, later_lines = split_shop(state.get("shop") or [])
        visible_calls = []
        wall = time.time()
        for row in state.get("callouts") or []:
            if len(row) >= 3 and wall - row[2] <= fade:
                visible_calls.append(row[1])
        focus = shop_alert or (visible_calls[-1] if visible_calls else "Watching timers, gold, CS, and item path.")
        alert_label.configure(text=focus)

        name, text, _remain, color = next_objective(state)
        obj_name.configure(text=name, fg=GOLD_BRIGHT if in_game else MUTED)
        obj_time.configure(text=text, fg=color)

        now_t = state.get("t")
        spawns = state.get("spawns") or {}
        labels = {
            "dragon": "ELD" if state.get("elder") else "DRG",
            "grubs": "GRB",
            "herald": "HER",
            "baron": "BAR",
        }
        for key, lbl in timer_labels.items():
            name_labels[key].configure(text=labels[key])
            remain = None
            if in_game and key in spawns and now_t is not None:
                remain = spawns[key] - now_t
            t_text, t_color = timer_style(remain if in_game else None)
            lbl.configure(text=t_text, fg=t_color)
            name_labels[key].configure(fg=t_color if t_text == "UP" else MUTED)

        gold_canvas.delete("all")
        if not in_game:
            gold_label.configure(text="Gold --", fg=MUTED)
            cs_label.configure(text="CS --", fg=MUTED)
            shop_next.configure(text="Queue up to load item plan.", fg=MUTED)
            shop_later.configure(text="")
        else:
            diff = state.get("gold_diff", 0) or 0
            prev = state.get("prev_gold_diff", diff) or 0
            gold_label.configure(text="Gold %s" % gold_text(diff, prev), fg=UP if diff >= 0 else DOWN)
            bar_w = max(10, width - 36)
            mid = bar_w / 2
            gold_canvas.create_rectangle(0, 2, bar_w, int(9 * scale), fill=TRACK, outline="")
            gold_canvas.create_line(mid, 0, mid, int(9 * scale), fill="#34445f")
            span = max(-1.0, min(1.0, diff / 5000.0)) * (bar_w / 2)
            fill = UP if diff >= 0 else DOWN
            if span >= 0:
                gold_canvas.create_rectangle(mid, 2, mid + span, int(9 * scale), fill=fill, outline="")
            else:
                gold_canvas.create_rectangle(mid + span, 2, mid, int(9 * scale), fill=fill, outline="")

            if state.get("position") == "UTILITY":
                cs_label.configure(text="Support", fg=MUTED)
            else:
                rate = state.get("cs_rate", 0) or 0
                target = state.get("cs_target", 8) or 8
                if rate >= target - 0.3:
                    c = UP
                elif rate >= target - 1.5:
                    c = SOON
                else:
                    c = DOWN
                cs_label.configure(text="CS %.1f/%g" % (rate, target), fg=c)

            if buy_lines:
                shop_next.configure(text="\n".join(buy_lines), fg=GOLD_BRIGHT)
            elif later_lines:
                shop_next.configure(text=later_lines[0], fg=TEXT)
                later_lines = later_lines[1:]
            else:
                shop_next.configure(text="No urgent buy. Track wave/objective.", fg=MUTED)
            shop_later.configure(text="\n".join(later_lines))

        for idx, lbl in enumerate(callout_labels):
            text = visible_calls[-(idx + 1)] if idx < len(visible_calls) else ""
            lbl.configure(text=text)

        if ticks["n"] % 20 == 0 and not hidden["value"]:
            root.attributes("-topmost", True)
            apply_style()
        root.after(100, refresh)

    def start_drag(event):
        if not move_mode["value"]:
            return
        drag["x"] = event.x_root - root.winfo_x()
        drag["y"] = event.y_root - root.winfo_y()

    def on_drag(event):
        if not move_mode["value"]:
            return
        root.geometry("+%d+%d" % (event.x_root - drag["x"], event.y_root - drag["y"]))

    def end_drag(_event):
        if move_mode["value"]:
            save_layout(layout["key"], root.winfo_x(), root.winfo_y(), width=int(layout["w"]), scale=scale)

    def bind_drag(widget):
        widget.bind("<Button-1>", start_drag)
        widget.bind("<B1-Motion>", on_drag)
        widget.bind("<ButtonRelease-1>", end_drag)
        for child in widget.winfo_children():
            bind_drag(child)

    bind_drag(shell)

    hotkeys = []
    if sys.platform.startswith("win"):
        if user32.RegisterHotKey(None, HOTKEY_HIDE_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_O):
            hotkeys.append(HOTKEY_HIDE_ID)
        else:
            print("Overlay hotkey Ctrl+Shift+O is already taken. Overlay still shows.", flush=True)
        if user32.RegisterHotKey(None, HOTKEY_MOVE_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_M):
            hotkeys.append(HOTKEY_MOVE_ID)
        else:
            print("Overlay move hotkey Ctrl+Shift+M is already taken. Use --overlay-edit to move.", flush=True)

    def on_close():
        if sys.platform.startswith("win"):
            for hotkey in hotkeys:
                user32.UnregisterHotKey(None, hotkey)
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
            for hotkey in hotkeys:
                user32.UnregisterHotKey(None, hotkey)
        stop.set()
