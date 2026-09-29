"""Small Windows integration helpers. Every function is a safe no-op on other platforms."""

import os
import subprocess
import sys
import webbrowser

IS_WIN = sys.platform.startswith("win")
APP_ID = "MacroGoblin"
MUTEX_NAME = "MacroGoblinSingleInstance"   # also used by the installer (AppMutex)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

_mutex = None


def single_instance():
    """True if this is the only running copy. Holds a named mutex for the life of the process."""
    global _mutex
    if not IS_WIN:
        return True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def focus_existing(title):
    """Bring the already-running window forward (used when a second copy is launched)."""
    if not IS_WIN:
        return False
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def enable_dpi_awareness():
    """Crisp text on 125-200% displays. Must run before the first Tk window."""
    if not IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_user_model_id():
    """Own taskbar identity, so the taskbar shows our icon instead of Python's."""
    if not IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ATXGreene.MacroGoblin")
    except Exception:
        pass


def dark_title_bar(tk_root):
    """Dark window chrome on Windows 10 20H1+ and 11."""
    if not IS_WIN:
        return
    import ctypes
    try:
        tk_root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(tk_root.winfo_id()) or tk_root.winfo_id()
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


def launch_command():
    """Command line used for 'Start with Windows'."""
    if getattr(sys, "frozen", False):
        return '"%s" --minimized' % sys.executable
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return '"%s" "%s" --minimized' % (pythonw, os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py")))


def autostart_enabled():
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_ID)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except OSError:
                    pass
        return True
    except OSError:
        return False


def open_path(path):
    if not os.path.splitext(path)[1]:
        os.makedirs(path, exist_ok=True)
    if IS_WIN:
        os.startfile(path)  # noqa: S606 - opens a local folder or file the user asked for
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_url(url):
    webbrowser.open(url)
