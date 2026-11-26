"""Tkinter window. Logic lives in core.py; this file only draws and wires it."""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, core
from .recycle import send_to_recycle_bin

THEMES = {
    "light": {"bg": "#ffffff", "fg": "#1d1d1f", "sub": "#6e6e73", "panel": "#f4f4f6", "sel": "#cfe3ff", "warn": "#d9382f"},
    "dark": {"bg": "#1e1e20", "fg": "#f2f2f2", "sub": "#98989d", "panel": "#2a2a2d", "sel": "#2f4d7a", "warn": "#ff6b5f"},
}
MAX_ROWS = 500


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"DustPilot {__version__}")
        self.geometry("1040x700")
        self.minsize(860, 520)
        self.items = []
        self.selected = set()          # item ids; empty after every scan
        self.root_dir = None
        self.generation = 0
        self.cancel = threading.Event()
        self.busy = False
        self.results = queue.Queue()
        self.theme = tk.StringVar(value="light")
        self.category = tk.StringVar(value=core.ALL_ITEMS)
        self.sort = tk.StringVar(value="Size")
        self.search = tk.StringVar()
        self.status = tk.StringVar(value="Choose a folder to begin. Nothing is selected until you choose it.")
        self.summary = tk.StringVar(value="0 selected")
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._build()
        self._apply_theme()
        self.category.trace_add("write", lambda *_: self._refresh())
        self.sort.trace_add("write", lambda *_: self._refresh())
        self.search.trace_add("write", lambda *_: self._refresh())
        self.after(100, self._poll)

    # ---- layout ----
    def _build(self):
        top = ttk.Frame(self, padding=(14, 12))
        top.pack(fill="x")
        ttk.Label(top, text="DustPilot", style="Title.TLabel").pack(side="left")
        self.path_label = ttk.Label(top, text="No folder chosen", style="Sub.TLabel")
        self.path_label.pack(side="left", padx=14)
        ttk.Button(top, text="Dark / Light", command=self._toggle_theme).pack(side="right", padx=(8, 0))
        self.choose_btn = ttk.Button(top, text="Choose Folder…", command=self.choose_folder)
        self.choose_btn.pack(side="right")

        bar = ttk.Frame(self, padding=(14, 4))
        bar.pack(fill="x")
        ttk.Entry(bar, textvariable=self.search, width=28).pack(side="left")
        ttk.Combobox(bar, textvariable=self.category, state="readonly", width=14,
                     values=[core.ALL_ITEMS] + core.CATEGORIES).pack(side="left", padx=8)
        ttk.Combobox(bar, textvariable=self.sort, state="readonly", width=14, values=core.SORTS).pack(side="left")
        ttk.Button(bar, text="Export CSV…", command=self.export_csv).pack(side="right")
        ttk.Button(bar, text="Clear Selection", command=self._clear_selection).pack(side="right", padx=8)
        ttk.Button(bar, text="Select Visible", command=self._select_visible).pack(side="right")

        mid = ttk.Frame(self, padding=(14, 6))
        mid.pack(fill="both", expand=True)
        cols = ("sel", "name", "category", "size", "path")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, label, w, anchor in (("sel", "", 36, "center"), ("name", "Name", 230, "w"), ("category", "Category", 100, "w"),
                                    ("size", "Size", 90, "e"), ("path", "Path and reason", 520, "w")):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == "path"))
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Double-Button-1>", self._reveal)

        foot = ttk.Frame(self, padding=(14, 10))
        foot.pack(fill="x")
        ttk.Label(foot, textvariable=self.status, style="Sub.TLabel").pack(side="left")
        self.trash_btn = ttk.Button(foot, text="Move to Recycle Bin…", command=self.trash_selected)
        self.trash_btn.pack(side="right")
        ttk.Label(foot, textvariable=self.summary).pack(side="right", padx=12)

    def _apply_theme(self):
        t = THEMES[self.theme.get()]
        self.configure(bg=t["bg"])
        s = self.style
        s.configure(".", background=t["bg"], foreground=t["fg"], fieldbackground=t["panel"])
        s.configure("TFrame", background=t["bg"])
        s.configure("TLabel", background=t["bg"], foreground=t["fg"])
        s.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        s.configure("Sub.TLabel", foreground=t["sub"])
        s.configure("TButton", background=t["panel"], foreground=t["fg"], padding=6)
        s.map("TButton", background=[("active", t["sel"])])
        s.configure("Treeview", background=t["bg"], fieldbackground=t["bg"], foreground=t["fg"], rowheight=26)
        s.configure("Treeview.Heading", background=t["panel"], foreground=t["fg"])
        s.map("Treeview", background=[("selected", t["sel"])], foreground=[("selected", t["fg"])])
        self.option_add("*TCombobox*Listbox.background", t["panel"])
        self.option_add("*TCombobox*Listbox.foreground", t["fg"])

    def _toggle_theme(self):
        self.theme.set("dark" if self.theme.get() == "light" else "light")
        self._apply_theme()

    # ---- data ----
    def _visible(self):
        return core.sort_items(core.visible(self.items, self.category.get(), self.search.get()), self.sort.get())

    def _targets(self):
        return core.trash_targets(self.items, self.selected, self.category.get(), self.search.get())

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        vis = self._visible()
        for i in vis[:MAX_ROWS]:
            mark = "☑" if i.id in self.selected else "☐"
            self.tree.insert("", "end", iid=i.id, values=(mark, i.name, i.category, i.size_text, f"{i.path}  |  {i.reason}"))
        t = self._targets()
        self.summary.set(f"{len(t)} selected · {core.format_bytes(sum(i.bytes for i in t))}")
        self.trash_btn.state(["!disabled"] if t and not self.busy else ["disabled"])
        if len(vis) > MAX_ROWS:
            self.status.set(f"Showing first {MAX_ROWS} of {len(vis)}. Narrow with search or category.")

    def _toggle_id(self, iid):
        if iid in self.selected:
            self.selected.discard(iid)
        else:
            self.selected.add(iid)
        self._refresh()

    def _on_click(self, event):
        if self.tree.identify("region", event.x, event.y) == "cell" and self.tree.identify_column(event.x) == "#1":
            iid = self.tree.identify_row(event.y)
            if iid:
                self._toggle_id(iid)
                return "break"

    def _on_space(self, _event):
        sel = self.tree.selection()
        if sel:
            self._toggle_id(sel[0])

    def _select_visible(self):
        self.selected.update(i.id for i in self._visible())
        self._refresh()

    def _clear_selection(self):
        self.selected.clear()
        self._refresh()

    def _reveal(self, _event):
        sel = self.tree.selection()
        item = next((i for i in self.items if sel and i.id == sel[0]), None)
        if item and os.name == "nt":
            os.startfile(os.path.dirname(item.path))  # type: ignore[attr-defined]

    # ---- actions ----
    def choose_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder to analyse")
        if folder:
            self.start_scan(folder)

    def start_scan(self, folder):
        self.cancel.set()                    # stop any older scan
        self.cancel = cancel = threading.Event()
        self.generation += 1
        gen = self.generation
        self.root_dir = folder
        self.items, self.selected = [], set()
        self.path_label.config(text=folder)
        self.status.set("Scanning…")
        self.busy = True
        self._refresh()

        def work():
            res = core.scan(folder, core.ScanOptions(), cancel.is_set)
            self.results.put(("scan", gen, res))
        threading.Thread(target=work, daemon=True).start()

    def trash_selected(self):
        targets = self._targets()
        if not targets or self.busy:
            return
        total = core.format_bytes(sum(i.bytes for i in targets))
        if not messagebox.askyesno("Move to Recycle Bin?",
                                   f"Move {len(targets)} item(s), {total}, to the Recycle Bin?\n\nYou can restore them from the Recycle Bin.",
                                   icon="warning"):
            return
        self.busy = True
        self.status.set(f"Moving {len(targets)} item(s) to the Recycle Bin…")
        self._refresh()

        def work():
            self.results.put(("trash", 0, core.trash_items(targets, send_to_recycle_bin)))
        threading.Thread(target=work, daemon=True).start()

    def export_csv(self):
        vis = self._visible()
        if not vis:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="DustPilot-report.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel reads UTF-8
                f.write(core.to_csv(vis))
            self.status.set(f"Report saved: {os.path.basename(path)}")

    def _poll(self):
        try:
            while True:
                kind, gen, res = self.results.get_nowait()
                if kind == "scan" and gen == self.generation and not res.cancelled:
                    self.items = res.items
                    self.busy = False
                    note = " · stopped at the entry limit, results are partial" if res.truncated else ""
                    self.status.set(f"Analysis complete · {len(res.items)} review candidates · {res.files_checked} files checked{note}")
                    self._refresh()
                elif kind == "trash":
                    self.items = [i for i in self.items if i.id not in res.moved_ids]
                    self.selected -= res.moved_ids
                    self.busy = False
                    self.status.set(f"Moved {len(res.moved_ids)} to the Recycle Bin · {len(res.failures)} failed")
                    self._refresh()
                    if res.failures:
                        messagebox.showwarning("Some items could not be moved", "\n".join(res.failures[:5]))
        except queue.Empty:
            pass
        self.after(100, self._poll)


def main():
    App().mainloop()
