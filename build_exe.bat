@echo off
REM Builds dist\DustPilot.exe (single file). Needs Python 3.9+ on Windows.
python -m pip install --quiet pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name DustPilot run_dustpilot.py || exit /b 1
echo Built dist\DustPilot.exe
