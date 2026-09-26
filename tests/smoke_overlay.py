"""Off-screen overlay style check. Does not touch the League process."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import overlay

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080


def main():
    import tkinter as tk
    import lol_coach

    bus = lol_coach.UiBus()
    stop = __import__("threading").Event()
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("180x80+-2400+-2400")
    root.configure(bg="magenta")
    try:
        root.attributes("-transparentcolor", "magenta")
    except tk.TclError as exc:
        print("TRANSPARENTCOLOR_FAIL", exc)
    tk.Label(root, text="style check", bg="#141820", fg="#e7e5e4").pack()
    root.update_idletasks()
    hwnd = overlay.top_hwnd(root)
    style = overlay.apply_exstyle(hwnd, click_through=True)
    hotkey = overlay.user32.RegisterHotKey(None, overlay.HOTKEY_ID, overlay.MOD_CONTROL | overlay.MOD_SHIFT | overlay.MOD_NOREPEAT, overlay.VK_O)
    overlay.user32.UnregisterHotKey(None, overlay.HOTKEY_ID)
    root.destroy()
    print("HWND", hwnd)
    print("EXSTYLE", hex(style & 0xFFFFFFFF))
    print("LAYERED", bool(style & WS_EX_LAYERED))
    print("TRANSPARENT", bool(style & WS_EX_TRANSPARENT))
    print("TOOLWINDOW", bool(style & WS_EX_TOOLWINDOW))
    print("HOTKEY_REGISTERED", bool(hotkey))
    if not (style & WS_EX_TRANSPARENT and style & WS_EX_TOOLWINDOW and style & WS_EX_LAYERED):
        raise SystemExit(2)
    if not hotkey:
        raise SystemExit(3)
    print("OVERLAY_SMOKE_OK")


if __name__ == "__main__":
    main()
