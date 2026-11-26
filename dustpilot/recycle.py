"""Move a file to the Windows Recycle Bin (never a permanent delete)."""
import ctypes
import os
import sys
from ctypes import wintypes

_FO_DELETE = 0x3
_FOF_ALLOWUNDO = 0x40        # use the Recycle Bin
_FOF_NOCONFIRMATION = 0x10
_FOF_NOERRORUI = 0x400
_FOF_SILENT = 0x4


def send_to_recycle_bin(path: str) -> None:
    if sys.platform != "win32":
        raise OSError("Recycle Bin is only available on Windows")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    full = os.path.abspath(path)
    if not os.path.exists(full):
        raise FileNotFoundError(full)
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = _FO_DELETE
    op.pFrom = full + "\0"   # double-null terminated list (the second null is added by ctypes)
    op.pTo = None
    # FOF_ALLOWUNDO is what makes this a Recycle Bin move instead of a delete.
    op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_NOERRORUI | _FOF_SILENT
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Recycle Bin move failed (code {code})")
    if os.path.exists(full):
        raise OSError("File is still in place after the Recycle Bin move")
