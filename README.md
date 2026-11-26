# DustPilot for Windows

Pick a folder. DustPilot lists files that are likely clutter. You choose what to remove, and it goes to the **Recycle Bin**. Nothing is deleted permanently, nothing is uploaded, nothing is pre-selected.

Windows version of [DustPilot for macOS](https://github.com/iamjohnyogesh-bit/DustPilot). Python 3.9+, standard library only (no pip packages to run it).

## What it finds
| Category | Rule |
|---|---|
| Caches | Any file inside a folder named Cache, Caches, Code Cache, GPUCache, INetCache, ShaderCache or DawnCache (any depth below the folder you chose) |
| Logs | `.log` files |
| Temporary | `.tmp`, `.temp`, `.bak`, `.old`, `.swp`, `.dmp` |
| Large files | 250 MB or more |
| Old files | 50 MB or more, not modified for 365 days |
| Duplicates | Same size, same SHA-256, then a byte-for-byte check, 1 MB or more. The oldest copy is kept and not listed |

Results are review candidates, not a claim that a file is safe to delete.

## Features
- Folder picker, local scan, a new scan cancels the old one
- Filter by category, search, sort by size, name or date
- Nothing pre-selected. "Move to Recycle Bin" acts only on items that are selected and visible; a confirmation shows the count and size
- Removal runs in the background; one failure does not stop the rest
- CSV export (Excel-friendly, formula-safe)
- Light and dark theme (button in the top bar)
- Skips hidden files, symlinks and junctions. Stops at 100,000 entries and says so

## Run
```bat
python -m dustpilot
```

## Build a single .exe
```bat
build_exe.bat
```
Creates `dist\DustPilot.exe` (PyInstaller). Windows SmartScreen may warn because the exe is not code-signed.

## Test
```bash
python -m unittest discover -s tests -v
```

## Verification status
The scanning, filtering, duplicate, CSV and trash-error logic has 17 unit tests that pass on Linux (Python 3). The Tkinter window and the real Recycle Bin call (`SHFileOperationW`) only work on Windows and have **not** been run yet. GitHub Actions runs the tests on Windows and builds the .exe on every push; check that first.

## License
MIT, see `LICENSE`.
