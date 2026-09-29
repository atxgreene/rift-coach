# PyInstaller build for Macro Goblin (Windows).
#   pyinstaller packaging/macrogoblin.spec --noconfirm --clean
# Produces dist/MacroGoblin/ with two executables sharing one runtime:
#   MacroGoblin.exe     launcher window (no console)
#   MacroGoblinCLI.exe  command line
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "app-icon.ico")
VERSION_FILE = os.path.join(ROOT, "packaging", "version_info.txt")

ASSETS = ["app-icon.ico", "app-icon-64.png", "app-icon-128.png", "app-icon-256.png", "app-icon-512.png",
          "live-mark-128.png", "live-mark-512.png", "favicon-mark.png"]
datas = [(os.path.join(ROOT, "assets", name), "assets") for name in ASSETS]
datas += [
    (os.path.join(ROOT, "tests", "fixtures", "real", "kaisa-bot-win.jsonl.gz"), os.path.join("tests", "fixtures", "real")),
    (os.path.join(ROOT, "tests", "fixtures", "ddragon.json.gz"), os.path.join("tests", "fixtures")),
]

a = Analysis(
    [os.path.join(ROOT, "entry.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["app", "lol_coach", "overlay", "web_dash", "settings", "updates", "winplat", "shop", "patterns"],
    excludes=["pydoc_data", "lib2to3", "test", "idlelib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(exclude_binaries=True, icon=ICON, version=VERSION_FILE, upx=False)
gui = EXE(pyz, a.scripts, [], name="MacroGoblin", console=False, **common)
cli = EXE(pyz, a.scripts, [], name="MacroGoblinCLI", console=True, **common)

coll = COLLECT(gui, cli, a.binaries, a.datas, name="MacroGoblin", upx=False)
