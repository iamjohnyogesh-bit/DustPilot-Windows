"""Scanning, filtering, selection and CSV export. Standard library only, no GUI imports."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import stat
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

CACHES, LOGS, TEMP, LARGE, OLD, DUPES = "Caches", "Logs", "Temporary", "Large files", "Old files", "Duplicates"
CATEGORIES = [CACHES, LOGS, TEMP, LARGE, OLD, DUPES]
ALL_ITEMS = "All items"

CACHE_FOLDERS = {"cache", "caches", "code cache", "gpucache", "inetcache", "shadercache", "dawncache"}
TEMP_EXTENSIONS = {".tmp", ".temp", ".bak", ".old", ".swp", ".dmp"}
MB = 1024 * 1024
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass
class ScanOptions:
    large_bytes: int = 250 * MB
    max_entries: int = 100_000
    stale_days: int = 365          # 0 disables
    stale_min_bytes: int = 50 * MB
    duplicate_min_bytes: int = 1 * MB  # 0 disables
    now: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Item:
    path: str
    category: str
    bytes: int
    modified: Optional[float]
    reason: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def size_text(self) -> str:
        return format_bytes(self.bytes)


@dataclass
class ScanResult:
    items: List[Item] = field(default_factory=list)
    files_checked: int = 0
    bytes_checked: int = 0
    truncated: bool = False
    cancelled: bool = False


def format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def _is_hidden(entry: os.DirEntry, st: os.stat_result) -> bool:
    if entry.name.startswith("."):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_HIDDEN)


def _is_link(entry: os.DirEntry, st: os.stat_result) -> bool:
    # Symlinks and Windows junctions / reparse points are never followed.
    return entry.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def classify(path: str, size: int, modified: Optional[float], rel_folders: Iterable[str], opts: ScanOptions) -> Optional[Tuple[str, str]]:
    """Return (category, reason) for a file or None. Any folder between the chosen root and the file counts as a cache folder."""
    if any(f.lower() in CACHE_FOLDERS for f in rel_folders):
        return CACHES, "Stored inside a cache-named folder"
    ext = os.path.splitext(path)[1].lower()
    if ext == ".log":
        return LOGS, "Log file; check whether it is still needed"
    if ext in TEMP_EXTENSIONS:
        return TEMP, "Temporary or backup-style extension; may hold data you want"
    if size >= opts.large_bytes:
        return LARGE, "Large file; size alone does not mean it is safe to remove"
    if opts.stale_days > 0 and size >= opts.stale_min_bytes and modified is not None \
            and modified < opts.now - opts.stale_days * 86400:
        return OLD, f"Not modified for over {opts.stale_days} days; review before removing"
    return None


def scan(root: str, opts: Optional[ScanOptions] = None, is_cancelled: Callable[[], bool] = lambda: False) -> ScanResult:
    """Walk root and return review candidates. Read-only: never changes or deletes anything."""
    opts = opts or ScanOptions()
    res = ScanResult()
    root = os.path.abspath(root)
    uncategorised: Dict[int, List[Tuple[str, Optional[float]]]] = {}
    entries = 0
    stack: List[Tuple[str, Tuple[str, ...]]] = [(root, ())]
    while stack:
        folder, rel = stack.pop()
        try:
            it = list(os.scandir(folder))
        except OSError:
            continue
        for entry in it:
            if is_cancelled():
                res.cancelled = True
                return res
            entries += 1
            if entries > opts.max_entries:
                res.truncated = True
                stack.clear()
                break
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if _is_hidden(entry, st) or _is_link(entry, st):
                continue
            if stat.S_ISDIR(st.st_mode):
                stack.append((entry.path, rel + (entry.name,)))
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            res.files_checked += 1
            res.bytes_checked += st.st_size
            hit = classify(entry.path, st.st_size, st.st_mtime, rel, opts)
            if hit:
                res.items.append(Item(entry.path, hit[0], st.st_size, st.st_mtime, hit[1]))
            elif opts.duplicate_min_bytes > 0 and st.st_size >= opts.duplicate_min_bytes:
                uncategorised.setdefault(st.st_size, []).append((entry.path, st.st_mtime))
    if opts.duplicate_min_bytes > 0:
        res.items.extend(find_duplicates(uncategorised, is_cancelled, res))
        if res.cancelled:
            return res
    res.items.sort(key=lambda i: i.bytes, reverse=True)
    return res


def _hash_file(path: str) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _same_content(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                ca, cb = fa.read(1 << 20), fb.read(1 << 20)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def find_duplicates(by_size: Dict[int, List[Tuple[str, Optional[float]]]], is_cancelled: Callable[[], bool], res: ScanResult) -> List[Item]:
    """Same size, same SHA-256, then a byte-for-byte check. The oldest copy is kept and not listed."""
    out: List[Item] = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        if is_cancelled():
            res.cancelled = True
            return out
        buckets: Dict[str, List[Tuple[str, Optional[float]]]] = {}
        for path, mtime in files:
            digest = _hash_file(path)
            if digest:
                buckets.setdefault(digest, []).append((path, mtime))
        for group in buckets.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda f: (f[1] if f[1] is not None else float("inf"), f[0]))
            keep = group[0]
            for path, mtime in group[1:]:
                if _same_content(keep[0], path):
                    out.append(Item(path, DUPES, size, mtime,
                                    f"Identical to {os.path.basename(keep[0])} (kept: {os.path.dirname(keep[0])})"))
    return out


# ---- review: filtering, sorting, selection ----

SORTS = ("Size", "Name", "Date modified")


def visible(items: List[Item], category: str = ALL_ITEMS, search: str = "") -> List[Item]:
    q = search.lower()
    return [i for i in items
            if (category == ALL_ITEMS or i.category == category)
            and (not q or q in i.name.lower() or q in i.path.lower())]


def sort_items(items: List[Item], order: str = "Size") -> List[Item]:
    if order == "Name":
        return sorted(items, key=lambda i: i.name.lower())
    if order == "Date modified":
        return sorted(items, key=lambda i: i.modified or 0)
    return sorted(items, key=lambda i: i.bytes, reverse=True)


def trash_targets(items: List[Item], selected: Set[str], category: str = ALL_ITEMS, search: str = "") -> List[Item]:
    """Selected AND visible, so a filter can never hide something that still gets removed."""
    return [i for i in visible(items, category, search) if i.id in selected]


def to_csv(items: List[Item]) -> str:
    def safe(v: str) -> str:
        # Stop spreadsheet apps from running a file name that starts with a formula character.
        return "'" + v if v[:1] in ("=", "+", "-", "@") else v
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(["Name", "Category", "Bytes", "Modified", "Path", "Reason"])
    for i in items:
        mod = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(i.modified)) if i.modified else ""
        w.writerow([safe(i.name), i.category, i.bytes, mod, safe(i.path), i.reason])
    return buf.getvalue()


# ---- removing ----

@dataclass
class TrashOutcome:
    moved_ids: Set[str] = field(default_factory=set)
    failures: List[str] = field(default_factory=list)


def trash_items(items: List[Item], send_to_trash: Callable[[str], None]) -> TrashOutcome:
    """Send each item with the given function. One failure does not stop the rest."""
    out = TrashOutcome()
    for item in items:
        try:
            send_to_trash(item.path)
            out.moved_ids.add(item.id)
        except Exception as e:  # noqa: BLE001 - report every failure to the user
            out.failures.append(f"{item.name}: {e}")
    return out
