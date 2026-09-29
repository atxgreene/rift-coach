"""Write packaging/version_info.txt (Windows file properties) from lol_coach.__version__."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import lol_coach  # noqa: E402

numbers = [int(part) for part in lol_coach.__version__.split(".")[:3]] + [0]
while len(numbers) < 4:
    numbers.append(0)
dotted = ".".join(str(n) for n in numbers)

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'ATXGreene'),
      StringStruct('FileDescription', 'Macro Goblin - live macro coach for League of Legends'),
      StringStruct('FileVersion', '{d}'),
      StringStruct('InternalName', 'MacroGoblin'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 ATXGreene'),
      StringStruct('OriginalFilename', 'MacroGoblin.exe'),
      StringStruct('ProductName', 'Macro Goblin'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

with open(os.path.join(HERE, "version_info.txt"), "w", encoding="utf-8") as handle:
    handle.write(TEMPLATE.format(t=", ".join(str(n) for n in numbers), d=dotted, v=lol_coach.__version__))
print("version_info.txt ->", dotted)
