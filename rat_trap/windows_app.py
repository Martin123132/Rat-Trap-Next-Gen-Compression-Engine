"""Small, self-contained Windows desktop interface for Rat-Trap."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

try:
    from . import gmw_tool, repository_engine
except ImportError:  # Allows direct execution while developing.
    import gmw_tool  # type: ignore
    import repository_engine  # type: ignore


APP_NAME = "Rat-Trap"
APP_VERSION = "5.2.0"
PROFILE_OPTIONS = {
    "Balanced - Zstandard 6 (recommended)": "balanced",
    "Fast - Zstandard 3": "fast",
    "Smallest - Zstandard 19 (slow)": "smallest",
    "Queryable Vault - searchable files and data tables": "vault",
}
PROFILE_NOTES = {
    "balanced": "Best verified all-round result. Solid compression automatically stores exact duplicate files once.",
    "fast": "Faster solid compression with a modest size trade-off.",
    "smallest": "Tries hardest for the smallest file and also removes exact duplicates. Can be much slower.",
    "vault": "Search files and turn CSV, TSV, JSON, JSONL, and .data files into queryable SQLite tables.",
}
ARCHIVE_TYPES = [
    ("Rat-Trap archives", "*.gmw"),
    ("SQLite databases", "*.db"),
    ("All files", "*.*"),
]


def _format_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_time_ns(value: int) -> str:
    return dt.datetime.fromtimestamp(value / 1_000_000_000).strftime(
        "%d %b %Y, %H:%M"
    )


class RatTrapApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.busy = False
        self.action_buttons: list[ttk.Button] = []
        self._saved_action_states: dict[ttk.Button, str] = {}

        root.title(f"{APP_NAME} {APP_VERSION}")
        root.geometry("1100x760")
        root.minsize(900, 650)

        self._configure_style()
        self._build_ui()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground="#555555")
        style.configure("Heading.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 9))
        style.configure("TNotebook.Tab", padding=(18, 8))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(24, 18, 24, 14))
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text=APP_NAME, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="Back up, compress, search, restore, and share your files.",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(0, 14))

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        self._build_create_tab()
        self._build_repository_tab()
        self._build_vault_tab()
        self._build_data_tab()
        self._build_extract_tab()
        self._build_inspect_tab()

        status = ttk.Frame(outer)
        status.pack(fill=tk.X, pady=(14, 0))
        self.status_text = tk.StringVar(value="Ready")
        ttk.Label(status, textvariable=self.status_text).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=180)
        self.progress.pack(side=tk.RIGHT)

        ttk.Label(
            outer,
            text=f"Version {APP_VERSION}  |  Personal and academic use",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.E, pady=(8, 0))

    def _new_tab(self, title: str) -> ttk.Frame:
        tab = ttk.Frame(self.tabs, padding=24)
        self.tabs.add(tab, text=title)
        tab.columnconfigure(1, weight=1)
        return tab

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=8, padx=(0, 12))
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, pady=8)
        browse_button = ttk.Button(parent, text="Browse...", command=command)
        browse_button.grid(
            row=row, column=2, sticky=tk.E, pady=8, padx=(10, 0)
        )
        self.action_buttons.append(browse_button)

    def _action_button(
        self, parent: ttk.Frame, text: str, command: Callable[[], None], row: int
    ) -> None:
        button = ttk.Button(parent, text=text, command=command, style="Action.TButton")
        button.grid(row=row, column=0, columnspan=3, sticky=tk.E, pady=(24, 0))
        self.action_buttons.append(button)

    def _build_create_tab(self) -> None:
        tab = self._new_tab("Create archive")
        ttk.Label(tab, text="Create a GMW archive", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )
        ttk.Label(
            tab,
            text="Choose a folder and save the archive somewhere outside that folder.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 16))

        self.source_folder = tk.StringVar()
        self.create_archive = tk.StringVar()
        self.profile_label = tk.StringVar(value=next(iter(PROFILE_OPTIONS)))
        self.profile_note = tk.StringVar(value=PROFILE_NOTES["balanced"])
        self._path_row(tab, 2, "Source folder", self.source_folder, self._choose_source)
        self._path_row(tab, 3, "Save archive", self.create_archive, self._choose_create_archive)

        ttk.Label(tab, text="Format").grid(row=4, column=0, sticky=tk.W, pady=8, padx=(0, 12))
        profile_box = ttk.Combobox(
            tab,
            textvariable=self.profile_label,
            values=tuple(PROFILE_OPTIONS),
            state="readonly",
            width=42,
        )
        profile_box.grid(row=4, column=1, sticky=tk.W, pady=8)
        profile_box.bind("<<ComboboxSelected>>", self._profile_changed)
        ttk.Label(
            tab,
            textvariable=self.profile_note,
            style="Subtitle.TLabel",
            wraplength=560,
        ).grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=(2, 4))

        self._action_button(tab, "Create", self._start_create, 6)

    def _profile_changed(self, _event=None) -> None:
        profile = PROFILE_OPTIONS[self.profile_label.get()]
        self.profile_note.set(PROFILE_NOTES[profile])
        if self.source_folder.get() and self.create_archive.get():
            source = Path(self.source_folder.get())
            current = Path(self.create_archive.get())
            automatic_names = {
                source.parent / f"{source.name}.gmw",
                source.parent / f"{source.name}.vault.gmw",
            }
            if current in automatic_names:
                self.create_archive.set(str(source.parent / self._suggested_output_name(source)))

    def _suggested_output_name(self, source: Path) -> str:
        profile = PROFILE_OPTIONS[self.profile_label.get()]
        suffix = ".vault.gmw" if profile == "vault" else ".gmw"
        return f"{source.name}{suffix}"

    def _build_repository_tab(self) -> None:
        tab = self._new_tab("Backups & history")
        ttk.Label(
            tab, text="Deduplicated backups and file history", style="Heading.TLabel"
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 4))
        ttk.Label(
            tab,
            text=(
                "Keep many verified snapshots in one repository. Unchanged data is "
                "reused automatically; portable .gmw archives remain available."
            ),
            style="Subtitle.TLabel",
            wraplength=820,
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 8))

        self.repository_path = tk.StringVar()
        self.repository_source = tk.StringVar()
        self.repository_label = tk.StringVar()
        self.repository_search = tk.StringVar()
        self.repository_status = tk.StringVar(value="No repository open")
        self.repository_loaded_path: Path | None = None
        self.repository_snapshots: dict[
            str, repository_engine.SnapshotInfo
        ] = {}
        self.repository_history_snapshot_ids: dict[str, str] = {}

        self._path_row(
            tab,
            2,
            "Repository",
            self.repository_path,
            self._choose_repository,
        )
        repository_buttons = ttk.Frame(tab)
        repository_buttons.grid(
            row=3, column=0, columnspan=3, sticky=tk.EW, pady=(0, 5)
        )
        open_button = ttk.Button(
            repository_buttons,
            text="Open / refresh",
            command=self._start_repository_refresh,
        )
        open_button.pack(side=tk.LEFT)
        initialize_button = ttk.Button(
            repository_buttons,
            text="Initialize empty folder...",
            command=self._start_repository_initialize,
        )
        initialize_button.pack(side=tk.LEFT, padx=(8, 0))
        incomplete_button = ttk.Button(
            repository_buttons,
            text="Interrupted jobs...",
            command=self._start_repository_incomplete_jobs,
        )
        incomplete_button.pack(side=tk.LEFT, padx=(8, 0))
        issues_button = ttk.Button(
            repository_buttons,
            text="Integrity issues...",
            command=self._start_repository_issues,
        )
        issues_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            repository_buttons,
            textvariable=self.repository_status,
            style="Subtitle.TLabel",
        ).pack(side=tk.RIGHT)
        self.action_buttons.extend(
            (
                open_button,
                initialize_button,
                incomplete_button,
                issues_button,
            )
        )

        self._path_row(
            tab,
            4,
            "Folder to back up",
            self.repository_source,
            self._choose_repository_source,
        )
        ttk.Label(tab, text="Snapshot label").grid(
            row=5, column=0, sticky=tk.W, pady=5, padx=(0, 12)
        )
        label_entry = ttk.Entry(tab, textvariable=self.repository_label)
        label_entry.grid(row=5, column=1, sticky=tk.EW, pady=5)
        backup_button = ttk.Button(
            tab,
            text="Back up now",
            command=self._start_repository_snapshot,
            style="Action.TButton",
        )
        backup_button.grid(row=5, column=2, sticky=tk.E, padx=(10, 0), pady=5)
        self.action_buttons.append(backup_button)

        ttk.Separator(tab, orient=tk.HORIZONTAL).grid(
            row=6, column=0, columnspan=3, sticky=tk.EW, pady=(7, 8)
        )
        search_row = ttk.Frame(tab)
        search_row.grid(row=7, column=0, columnspan=3, sticky=tk.EW, pady=(0, 6))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="File/path history").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8)
        )
        search_entry = ttk.Entry(
            search_row, textvariable=self.repository_search
        )
        search_entry.grid(row=0, column=1, sticky=tk.EW)
        search_entry.bind(
            "<Return>", lambda _event: self._start_repository_search()
        )
        search_button = ttk.Button(
            search_row, text="Search", command=self._start_repository_search
        )
        search_button.grid(row=0, column=2, padx=(8, 0))
        show_snapshots_button = ttk.Button(
            search_row,
            text="Show snapshots",
            command=self._show_repository_snapshots,
        )
        show_snapshots_button.grid(row=0, column=3, padx=(6, 0))
        self.action_buttons.extend((search_button, show_snapshots_button))

        self.repository_result_tabs = ttk.Notebook(tab)
        self.repository_result_tabs.grid(
            row=8, column=0, columnspan=3, sticky=tk.NSEW
        )
        snapshot_frame = ttk.Frame(self.repository_result_tabs)
        history_frame = ttk.Frame(self.repository_result_tabs)
        self.repository_result_tabs.add(snapshot_frame, text="Snapshots")
        self.repository_result_tabs.add(history_frame, text="Search results")

        snapshot_frame.columnconfigure(0, weight=1)
        snapshot_frame.rowconfigure(0, weight=1)
        self.repository_snapshot_tree = ttk.Treeview(
            snapshot_frame,
            columns=("created", "label", "source", "files", "size", "changes", "pin", "id"),
            show="headings",
            selectmode="browse",
            height=7,
        )
        snapshot_headings = {
            "created": "Created",
            "label": "Label",
            "source": "Source",
            "files": "Files",
            "size": "Size",
            "changes": "Changes",
            "pin": "Pinned",
            "id": "Snapshot id",
        }
        for column, heading in snapshot_headings.items():
            self.repository_snapshot_tree.heading(column, text=heading)
        self.repository_snapshot_tree.column("created", width=125, anchor=tk.W)
        self.repository_snapshot_tree.column("label", width=145, anchor=tk.W)
        self.repository_snapshot_tree.column("source", width=145, anchor=tk.W)
        self.repository_snapshot_tree.column("files", width=55, anchor=tk.E)
        self.repository_snapshot_tree.column("size", width=75, anchor=tk.E)
        self.repository_snapshot_tree.column("changes", width=105, anchor=tk.E)
        self.repository_snapshot_tree.column("pin", width=50, anchor=tk.CENTER)
        self.repository_snapshot_tree.column("id", width=85, anchor=tk.W)
        self.repository_snapshot_tree.grid(row=0, column=0, sticky=tk.NSEW)
        snapshot_scroll = ttk.Scrollbar(
            snapshot_frame,
            orient=tk.VERTICAL,
            command=self.repository_snapshot_tree.yview,
        )
        snapshot_scroll.grid(row=0, column=1, sticky=tk.NS)
        self.repository_snapshot_tree.configure(
            yscrollcommand=snapshot_scroll.set
        )
        self.repository_snapshot_tree.bind(
            "<<TreeviewSelect>>", self._repository_snapshot_selected
        )

        history_frame.columnconfigure(0, weight=1)
        history_frame.rowconfigure(0, weight=1)
        self.repository_history_tree = ttk.Treeview(
            history_frame,
            columns=("created", "path", "type", "size", "label", "snapshot"),
            show="headings",
            selectmode="browse",
            height=7,
        )
        history_headings = {
            "created": "Snapshot date",
            "path": "Stored path",
            "type": "Type",
            "size": "Size",
            "label": "Snapshot label",
            "snapshot": "Snapshot id",
        }
        for column, heading in history_headings.items():
            self.repository_history_tree.heading(column, text=heading)
        self.repository_history_tree.column("created", width=125, anchor=tk.W)
        self.repository_history_tree.column("path", width=315, anchor=tk.W)
        self.repository_history_tree.column("type", width=70, anchor=tk.W)
        self.repository_history_tree.column("size", width=80, anchor=tk.E)
        self.repository_history_tree.column("label", width=140, anchor=tk.W)
        self.repository_history_tree.column("snapshot", width=85, anchor=tk.W)
        self.repository_history_tree.grid(row=0, column=0, sticky=tk.NSEW)
        history_scroll = ttk.Scrollbar(
            history_frame,
            orient=tk.VERTICAL,
            command=self.repository_history_tree.yview,
        )
        history_scroll.grid(row=0, column=1, sticky=tk.NS)
        self.repository_history_tree.configure(
            yscrollcommand=history_scroll.set
        )
        self.repository_history_tree.bind(
            "<Double-1>", self._open_repository_search_snapshot
        )

        action_row = ttk.Frame(tab)
        action_row.grid(row=9, column=0, columnspan=3, sticky=tk.EW, pady=(6, 5))
        restore_button = ttk.Button(
            action_row,
            text="Restore selected...",
            command=self._start_repository_restore,
        )
        restore_button.pack(side=tk.LEFT)
        self.repository_pin_button = ttk.Button(
            action_row,
            text="Pin selected",
            command=self._start_repository_pin_toggle,
        )
        self.repository_pin_button.pack(side=tk.LEFT, padx=(6, 0))
        export_button = ttk.Button(
            action_row,
            text="Export selected .gmw...",
            command=self._start_repository_export,
        )
        export_button.pack(side=tk.LEFT, padx=(6, 0))
        verify_full_button = ttk.Button(
            action_row,
            text="Full verify",
            command=lambda: self._start_repository_verify(full=True),
        )
        verify_full_button.pack(side=tk.RIGHT)
        verify_quick_button = ttk.Button(
            action_row,
            text="Quick verify",
            command=lambda: self._start_repository_verify(full=False),
        )
        verify_quick_button.pack(side=tk.RIGHT, padx=(0, 6))
        self.action_buttons.extend(
            (
                restore_button,
                self.repository_pin_button,
                export_button,
                verify_quick_button,
                verify_full_button,
            )
        )

        retention = ttk.LabelFrame(
            tab, text="Retention cleanup (always previews first)", padding=(10, 5)
        )
        retention.grid(
            row=10, column=0, columnspan=3, sticky=tk.EW, pady=(3, 0)
        )
        defaults = repository_engine.RetentionPolicy()
        self.repository_keep_last = tk.StringVar(value=str(defaults.keep_last))
        self.repository_keep_daily = tk.StringVar(value=str(defaults.keep_daily))
        self.repository_keep_weekly = tk.StringVar(value=str(defaults.keep_weekly))
        self.repository_keep_monthly = tk.StringVar(value=str(defaults.keep_monthly))
        retention_values = (
            ("Newest", self.repository_keep_last),
            ("Daily", self.repository_keep_daily),
            ("Weekly", self.repository_keep_weekly),
            ("Monthly", self.repository_keep_monthly),
        )
        for index, (label, variable) in enumerate(retention_values):
            ttk.Label(retention, text=label).grid(
                row=0, column=index * 2, padx=(0 if index == 0 else 10, 4)
            )
            ttk.Entry(retention, textvariable=variable, width=5).grid(
                row=0, column=index * 2 + 1
            )
        retention.columnconfigure(8, weight=1)
        preview_button = ttk.Button(
            retention,
            text="Preview cleanup...",
            command=self._start_repository_retention_preview,
        )
        preview_button.grid(row=0, column=9, sticky=tk.E)
        self.action_buttons.append(preview_button)

        tab.rowconfigure(8, weight=1)

    def _build_vault_tab(self) -> None:
        tab = self._new_tab("Search Vault")
        ttk.Label(tab, text="Search a queryable Vault", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )
        ttk.Label(
            tab,
            text="Search filenames and indexed text, preview a result, or export selected files.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        self.vault_archive = tk.StringVar()
        self.vault_query = tk.StringVar()
        self.vault_extension = tk.StringVar()
        self._path_row(tab, 2, "Vault", self.vault_archive, self._choose_vault_archive)

        search_row = ttk.Frame(tab)
        search_row.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(2, 10))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="Find").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.vault_search_entry = ttk.Entry(search_row, textvariable=self.vault_query)
        self.vault_search_entry.grid(row=0, column=1, sticky=tk.EW)
        self.vault_search_entry.bind("<Return>", lambda _event: self._start_vault_search())
        ttk.Label(search_row, text="Extension").grid(
            row=0, column=2, sticky=tk.W, padx=(12, 6)
        )
        ttk.Entry(search_row, textvariable=self.vault_extension, width=10).grid(
            row=0, column=3, sticky=tk.W
        )
        search_button = ttk.Button(search_row, text="Search", command=self._start_vault_search)
        search_button.grid(row=0, column=4, padx=(10, 0))
        all_button = ttk.Button(search_row, text="Show all", command=self._show_all_vault)
        all_button.grid(row=0, column=5, padx=(6, 0))
        self.action_buttons.extend((search_button, all_button))

        results_frame = ttk.Frame(tab)
        results_frame.grid(row=4, column=0, columnspan=3, sticky=tk.NSEW)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        self.vault_results = ttk.Treeview(
            results_frame,
            columns=("path", "type", "size", "indexed"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        self.vault_results.heading("path", text="Path")
        self.vault_results.heading("type", text="Type")
        self.vault_results.heading("size", text="Size")
        self.vault_results.heading("indexed", text="Text indexed")
        self.vault_results.column("path", width=430, anchor=tk.W)
        self.vault_results.column("type", width=170, anchor=tk.W)
        self.vault_results.column("size", width=90, anchor=tk.E)
        self.vault_results.column("indexed", width=90, anchor=tk.CENTER)
        self.vault_results.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar = ttk.Scrollbar(
            results_frame, orient=tk.VERTICAL, command=self.vault_results.yview
        )
        scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.vault_results.configure(yscrollcommand=scrollbar.set)
        self.vault_results.bind("<Double-1>", lambda _event: self._start_vault_preview())

        result_buttons = ttk.Frame(tab)
        result_buttons.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=(8, 8))
        preview_button = ttk.Button(
            result_buttons, text="Preview selected", command=self._start_vault_preview
        )
        preview_button.pack(side=tk.LEFT)
        extract_button = ttk.Button(
            result_buttons,
            text="Export selected files...",
            command=self._start_vault_extract_selected,
        )
        extract_button.pack(side=tk.LEFT, padx=(8, 0))
        self.vault_result_count = tk.StringVar(value="No Vault loaded")
        ttk.Label(
            result_buttons, textvariable=self.vault_result_count, style="Subtitle.TLabel"
        ).pack(side=tk.RIGHT)
        self.action_buttons.extend((preview_button, extract_button))

        self.vault_preview = tk.Text(
            tab,
            height=8,
            wrap=tk.WORD,
            relief=tk.FLAT,
            background="#f5f5f5",
            padx=12,
            pady=10,
            font=("Consolas", 9),
            state=tk.DISABLED,
        )
        self.vault_preview.grid(row=6, column=0, columnspan=3, sticky=tk.NSEW)
        tab.rowconfigure(4, weight=3)
        tab.rowconfigure(6, weight=2)

    def _build_data_tab(self) -> None:
        tab = self._new_tab("Data Tables")
        ttk.Label(tab, text="Query structured data", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )
        ttk.Label(
            tab,
            text="Browse imported rows without SQL, or run a read-only SELECT query and export the results.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 8))

        self.data_archive = tk.StringVar()
        self.data_source_label = tk.StringVar()
        self.data_column_label = tk.StringVar(value="All columns")
        self.data_sort_label = tk.StringVar(value="Original row order")
        self.data_search = tk.StringVar()
        self.data_descending = tk.BooleanVar(value=False)
        self.data_source_map: dict[str, object] = {}
        self.data_column_map: dict[str, str] = {"All columns": ""}
        self.data_sort_map: dict[str, str] = {"Original row order": ""}
        self.data_current_result = None
        self._path_row(tab, 2, "Vault", self.data_archive, self._choose_data_archive)

        source_row = ttk.Frame(tab)
        source_row.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(2, 8))
        source_row.columnconfigure(1, weight=1)
        ttk.Label(source_row, text="Data source").grid(row=0, column=0, padx=(0, 8))
        self.data_source_box = ttk.Combobox(
            source_row, textvariable=self.data_source_label, state="readonly"
        )
        self.data_source_box.grid(row=0, column=1, sticky=tk.EW)
        self.data_source_box.bind("<<ComboboxSelected>>", self._data_source_changed)
        load_button = ttk.Button(
            source_row, text="Load tables", command=self._start_load_data_sources
        )
        load_button.grid(row=0, column=2, padx=(8, 0))
        self.data_catalog_note = tk.StringVar(value="No Vault loaded")
        ttk.Label(
            source_row, textvariable=self.data_catalog_note, style="Subtitle.TLabel"
        ).grid(row=1, column=1, sticky=tk.W, pady=(4, 0))
        self.action_buttons.append(load_button)

        modes = ttk.Notebook(tab)
        modes.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(0, 8))
        browse = ttk.Frame(modes, padding=10)
        sql_frame = ttk.Frame(modes, padding=10)
        modes.add(browse, text="Browse / filter")
        modes.add(sql_frame, text="SQL query")

        browse.columnconfigure(1, weight=1)
        ttk.Label(browse, text="Find").grid(row=0, column=0, padx=(0, 6), sticky=tk.W)
        browse_search = ttk.Entry(browse, textvariable=self.data_search)
        browse_search.grid(row=0, column=1, sticky=tk.EW)
        browse_search.bind("<Return>", lambda _event: self._start_data_query())
        ttk.Label(browse, text="In").grid(row=0, column=2, padx=(10, 6))
        self.data_column_box = ttk.Combobox(
            browse, textvariable=self.data_column_label, state="readonly", width=22
        )
        self.data_column_box.grid(row=0, column=3)
        ttk.Label(browse, text="Sort").grid(row=1, column=0, padx=(0, 6), pady=(8, 0))
        self.data_sort_box = ttk.Combobox(
            browse, textvariable=self.data_sort_label, state="readonly"
        )
        self.data_sort_box.grid(row=1, column=1, sticky=tk.EW, pady=(8, 0))
        ttk.Checkbutton(
            browse, text="Descending", variable=self.data_descending
        ).grid(row=1, column=2, columnspan=2, sticky=tk.W, padx=(10, 0), pady=(8, 0))
        browse_button = ttk.Button(browse, text="Show rows", command=self._start_data_query)
        browse_button.grid(row=0, column=4, rowspan=2, padx=(10, 0))
        self.action_buttons.append(browse_button)

        sql_frame.columnconfigure(0, weight=1)
        self.data_sql = tk.Text(sql_frame, height=4, wrap=tk.NONE, font=("Consolas", 9))
        self.data_sql.grid(row=0, column=0, sticky=tk.EW)
        sql_button = ttk.Button(sql_frame, text="Run SELECT", command=self._start_sql_query)
        sql_button.grid(row=0, column=1, padx=(10, 0), sticky=tk.N)
        ttk.Label(
            sql_frame,
            text="Only SELECT and WITH queries are accepted; the Vault is always opened read-only.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        self.action_buttons.append(sql_button)

        result_frame = ttk.Frame(tab)
        result_frame.grid(row=5, column=0, columnspan=3, sticky=tk.NSEW)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.data_results = ttk.Treeview(result_frame, show="headings", height=13)
        self.data_results.grid(row=0, column=0, sticky=tk.NSEW)
        data_y = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.data_results.yview)
        data_y.grid(row=0, column=1, sticky=tk.NS)
        data_x = ttk.Scrollbar(result_frame, orient=tk.HORIZONTAL, command=self.data_results.xview)
        data_x.grid(row=1, column=0, sticky=tk.EW)
        self.data_results.configure(yscrollcommand=data_y.set, xscrollcommand=data_x.set)

        result_buttons = ttk.Frame(tab)
        result_buttons.grid(row=6, column=0, columnspan=3, sticky=tk.EW, pady=(8, 0))
        export_button = ttk.Button(
            result_buttons, text="Export results...", command=self._start_data_export
        )
        export_button.pack(side=tk.LEFT)
        self.data_result_count = tk.StringVar(value="No query run")
        ttk.Label(
            result_buttons, textvariable=self.data_result_count, style="Subtitle.TLabel"
        ).pack(side=tk.RIGHT)
        self.action_buttons.append(export_button)
        tab.rowconfigure(5, weight=1)

    def _build_extract_tab(self) -> None:
        tab = self._new_tab("Extract archive")
        ttk.Label(tab, text="Restore files", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )
        ttk.Label(
            tab,
            text="Extract every file from a GMW archive into a destination folder.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(0, 16))

        self.extract_archive = tk.StringVar()
        self.extract_folder = tk.StringVar()
        self._path_row(tab, 2, "Archive", self.extract_archive, self._choose_extract_archive)
        self._path_row(tab, 3, "Destination", self.extract_folder, self._choose_extract_folder)
        self._action_button(tab, "Extract files", self._start_extract, 4)

    def _build_inspect_tab(self) -> None:
        tab = self._new_tab("Inspect / export")
        ttk.Label(tab, text="Archive details", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8)
        )

        self.inspect_archive = tk.StringVar()
        self._path_row(tab, 1, "Archive", self.inspect_archive, self._choose_inspect_archive)

        button_row = ttk.Frame(tab)
        button_row.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(8, 12))
        inspect_button = ttk.Button(button_row, text="Load details", command=self._load_details)
        inspect_button.pack(side=tk.LEFT)
        export_button = ttk.Button(button_row, text="Export as ZIP...", command=self._start_export)
        export_button.pack(side=tk.LEFT, padx=(10, 0))
        self.action_buttons.extend((inspect_button, export_button))

        self.details = tk.Text(
            tab,
            height=14,
            wrap=tk.WORD,
            relief=tk.FLAT,
            background="#f5f5f5",
            padx=14,
            pady=12,
            font=("Consolas", 10),
            state=tk.DISABLED,
        )
        self.details.grid(row=3, column=0, columnspan=3, sticky=tk.NSEW)
        tab.rowconfigure(3, weight=1)

    def _choose_source(self) -> None:
        selected = filedialog.askdirectory(title="Choose the folder to archive")
        if not selected:
            return
        self.source_folder.set(selected)
        source = Path(selected)
        if not self.create_archive.get():
            self.create_archive.set(str(source.parent / self._suggested_output_name(source)))

    def _choose_create_archive(self) -> None:
        source = Path(self.source_folder.get()) if self.source_folder.get() else None
        selected = filedialog.asksaveasfilename(
            title="Save Rat-Trap archive",
            initialdir=str(source.parent) if source else None,
            initialfile=self._suggested_output_name(source) if source else "archive.gmw",
            defaultextension=".gmw",
            filetypes=ARCHIVE_TYPES,
        )
        if selected:
            self.create_archive.set(selected)

    def _choose_repository(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose a Rat-Trap repository or a new empty folder"
        )
        if selected:
            self.repository_path.set(selected)
            self.repository_loaded_path = None
            self.repository_status.set("Repository selected; choose Open / refresh")

    def _choose_repository_source(self) -> None:
        selected = filedialog.askdirectory(title="Choose the folder to back up")
        if selected:
            self.repository_source.set(selected)

    def _choose_extract_archive(self) -> None:
        selected = filedialog.askopenfilename(title="Open Rat-Trap archive", filetypes=ARCHIVE_TYPES)
        if not selected:
            return
        self.extract_archive.set(selected)
        archive = Path(selected)
        if not self.extract_folder.get():
            self.extract_folder.set(str(archive.parent / f"{archive.stem}_extracted"))

    def _choose_extract_folder(self) -> None:
        selected = filedialog.askdirectory(title="Choose the extraction destination")
        if selected:
            self.extract_folder.set(selected)

    def _choose_inspect_archive(self) -> None:
        selected = filedialog.askopenfilename(title="Open Rat-Trap archive", filetypes=ARCHIVE_TYPES)
        if selected:
            self.inspect_archive.set(selected)
            self._load_details()

    def _choose_vault_archive(self) -> None:
        selected = filedialog.askopenfilename(
            title="Open a queryable Rat-Trap Vault", filetypes=ARCHIVE_TYPES
        )
        if selected:
            self.vault_archive.set(selected)
            self.data_archive.set(selected)
            self._show_all_vault()

    def _choose_data_archive(self) -> None:
        selected = filedialog.askopenfilename(
            title="Open a structured Rat-Trap Vault", filetypes=ARCHIVE_TYPES
        )
        if selected:
            self.data_archive.set(selected)
            self.vault_archive.set(selected)
            self._start_load_data_sources()

    def _checked_data_archive(self) -> Path | None:
        value = self.data_archive.get().strip()
        archive = Path(value)
        if not value or not archive.is_file():
            messagebox.showwarning(APP_NAME, "Choose an existing queryable Vault first.")
            return None
        if not gmw_tool.is_vault_archive(archive):
            messagebox.showwarning(APP_NAME, "This archive is not a queryable Vault.")
            return None
        return archive

    def _checked_repository(self, *, require_open: bool = True) -> Path | None:
        value = self.repository_path.get().strip()
        if not value:
            messagebox.showwarning(APP_NAME, "Choose a repository folder first.")
            return None
        repository = Path(value).resolve()
        if require_open and self.repository_loaded_path != repository:
            messagebox.showwarning(
                APP_NAME,
                "Open or refresh this repository before using its history.",
            )
            return None
        return repository

    def _render_repository(
        self,
        repository: Path,
        info: repository_engine.RepositoryInfo,
        snapshots: list[repository_engine.SnapshotInfo],
    ) -> None:
        self.repository_path.set(str(repository))
        self.repository_loaded_path = repository
        self.repository_snapshots = {
            snapshot.snapshot_id: snapshot for snapshot in snapshots
        }
        for item_id in self.repository_snapshot_tree.get_children():
            self.repository_snapshot_tree.delete(item_id)
        for snapshot in snapshots:
            source_name = Path(snapshot.source_path).name or snapshot.source_path
            changes = (
                f"{snapshot.changed_file_count:,}"
                f" / -{snapshot.deleted_file_count:,}"
            )
            self.repository_snapshot_tree.insert(
                "",
                tk.END,
                iid=snapshot.snapshot_id,
                values=(
                    _format_time_ns(snapshot.created_at_ns),
                    snapshot.label or "(no label)",
                    source_name,
                    f"{snapshot.file_count:,}",
                    _format_size(snapshot.total_bytes),
                    changes,
                    "Yes" if snapshot.pinned else "",
                    snapshot.snapshot_id[:10],
                ),
            )
        warning = (
            f"  |  WARNING: {info.issue_count:,} integrity issue(s); "
            "run Verify"
            if info.issue_count
            else ""
        )
        self.repository_status.set(
            f"{info.snapshot_count:,} snapshot(s)  |  "
            f"{info.pack_count:,} pack(s)  |  "
            f"{info.object_count:,} object(s)  |  "
            f"{_format_size(info.repository_file_bytes)} repository files  |  "
            f"{_format_size(info.pack_file_bytes)} active pack files  |  "
            f"{_format_size(info.trash_file_bytes)} recoverable trash"
            f"{warning}"
        )
        self.repository_pin_button.config(text="Pin selected")
        self.repository_result_tabs.select(0)

    def _start_repository_initialize(self) -> None:
        repository = self._checked_repository(require_open=False)
        if repository is None:
            return
        if (repository / "repository.json").is_file():
            self._start_repository_refresh()
            return
        try:
            contains_files = repository.exists() and any(repository.iterdir())
        except OSError as exc:
            messagebox.showerror(
                APP_NAME, f"Could not inspect this folder.\n\n{exc}"
            )
            return
        if contains_files:
            messagebox.showwarning(
                APP_NAME,
                "Initialization needs a new or empty folder. This folder already "
                "contains other files.",
            )
            return
        if not messagebox.askyesno(
            APP_NAME,
            "Initialize this folder as a Rat-Trap backup repository?\n\n"
            f"{repository}",
        ):
            return

        def work():
            info = repository_engine.init_repository(repository)
            snapshots = repository_engine.list_snapshots(repository)
            return info, snapshots

        def done(result) -> None:
            info, snapshots = result
            self._render_repository(repository, info, snapshots)
            messagebox.showinfo(
                APP_NAME,
                "Backup repository is ready.\n\n"
                "Choose a source folder and select Back up now.",
            )

        self._run_task("Initializing backup repository...", work, done)

    def _start_repository_refresh(self) -> None:
        repository = self._checked_repository(require_open=False)
        if repository is None:
            return

        def work():
            return (
                repository_engine.repository_info(repository),
                repository_engine.list_snapshots(repository),
            )

        def done(result) -> None:
            info, snapshots = result
            self._render_repository(repository, info, snapshots)
            self.status_text.set("Backup history refreshed")

        self._run_task("Opening backup repository...", work, done)

    def _start_repository_incomplete_jobs(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return

        def work():
            return repository_engine.list_incomplete_jobs(repository)

        def done(result: object) -> None:
            jobs = list(result)
            if not jobs:
                messagebox.showinfo(
                    APP_NAME, "There are no interrupted backup jobs."
                )
                return
            by_id = {job.job_id: job for job in jobs}
            if len(jobs) == 1:
                selected = jobs[0]
            else:
                summary = "\n".join(
                    f"{job.job_id}  {job.completed_files}/{job.total_files}  "
                    f"{job.source_path}"
                    for job in jobs[:8]
                )
                selected_id = simpledialog.askstring(
                    APP_NAME,
                    "Interrupted backup jobs:\n\n"
                    f"{summary}\n\n"
                    "Enter the exact job id to move to recoverable trash:",
                    parent=self.root,
                )
                if not selected_id:
                    return
                selected = by_id.get(selected_id.strip())
                if selected is None:
                    messagebox.showwarning(
                        APP_NAME,
                        "That exact interrupted job id was not found.",
                    )
                    return
            if not messagebox.askyesno(
                APP_NAME,
                "Move this interrupted job to recoverable trash?\n\n"
                f"Job: {selected.job_id}\n"
                f"Source: {selected.source_path}\n"
                f"Progress: {selected.completed_files:,}/"
                f"{selected.total_files:,} files\n"
                f"Staged payload: "
                f"{_format_size(selected.staged_object_payload_bytes)}\n\n"
                "This does not remove any published snapshot.",
                icon=messagebox.WARNING,
            ):
                return

            def abandon_work():
                return repository_engine.abandon_incomplete_job(
                    repository, selected.job_id
                )

            def abandon_done(
                abandoned: repository_engine.AbandonJobResult,
            ) -> None:
                messagebox.showinfo(
                    APP_NAME,
                    "Interrupted work moved to recoverable trash.\n\n"
                    f"{abandoned.trash_path}",
                )
                self._start_repository_refresh()

            self._run_task(
                "Moving interrupted work to recoverable trash...",
                abandon_work,
                abandon_done,
            )

        self._run_task("Checking interrupted backup jobs...", work, done)

    def _start_repository_issues(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return

        def work():
            return repository_engine.list_repository_issues(repository)

        def done(result: object) -> None:
            issues = list(result)
            if not issues:
                messagebox.showinfo(
                    APP_NAME,
                    "No canonical artifact or missing-object issues were found.\n\n"
                    "Use Quick verify or Full verify for the corresponding "
                    "integrity check.",
                )
                return
            details = "\n\n".join(
                f"{issue.kind}: {issue.relpath}\n{issue.message}"
                for issue in issues[:12]
            )
            if len(issues) > 12:
                details += (
                    f"\n\n...and {len(issues) - 12:,} additional issue(s)."
                )
            messagebox.showwarning(
                APP_NAME,
                f"Repository integrity issues: {len(issues):,}\n\n"
                f"{details}\n\n"
                "Healthy unrelated snapshots remain available. Cleanup is "
                "blocked until these issues are resolved.",
            )

        self._run_task("Reading repository integrity issues...", work, done)

    def _start_repository_snapshot(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return
        source_value = self.repository_source.get().strip()
        label = self.repository_label.get().strip()
        if not source_value or not Path(source_value).is_dir():
            messagebox.showwarning(APP_NAME, "Choose an existing folder to back up.")
            return
        source = Path(source_value).resolve()

        def progress(event: dict[str, object]) -> None:
            completed = int(event.get("completed_files", 0))
            total = int(event.get("total_files", 0))
            phase = str(event.get("phase", "snapshot"))
            path = str(event.get("path", ""))
            if phase == "publish":
                detail = "Publishing verified snapshot..."
            elif path:
                detail = f"Backing up {completed:,}/{total:,}: {path}"
            else:
                detail = f"Preparing backup ({completed:,}/{total:,} files)..."
            self.root.after(
                0, lambda status=detail: self.status_text.set(status)
            )

        def launch(*, restart: bool) -> None:
            def work():
                try:
                    return repository_engine.create_snapshot(
                        repository,
                        source,
                        label=label,
                        restart=restart,
                        progress=progress,
                    )
                except repository_engine.SourceChangedError as exc:
                    return exc

            def done(result: object) -> None:
                if isinstance(result, repository_engine.SourceChangedError):
                    if messagebox.askyesno(
                        APP_NAME,
                        "The source changed after an earlier backup was interrupted.\n\n"
                        "Preserve that incomplete work in repository trash and "
                        "start a fresh snapshot of the folder as it is now?",
                        icon=messagebox.WARNING,
                    ):
                        launch(restart=True)
                    return
                snapshot = result
                if not isinstance(snapshot, repository_engine.SnapshotInfo):
                    raise RuntimeError("Backup returned an unexpected result")
                messagebox.showinfo(
                    APP_NAME,
                    "Backup completed and verified.\n\n"
                    f"Files: {snapshot.file_count:,}\n"
                    f"Snapshot size: {_format_size(snapshot.total_bytes)}\n"
                    f"Changed files: {snapshot.changed_file_count:,}\n"
                    f"New pack file: {_format_size(snapshot.new_pack_file_bytes)}\n"
                    f"Compressed object payload: "
                    f"{_format_size(snapshot.new_object_payload_bytes)}\n"
                    f"Existing data reused: {_format_size(snapshot.reused_bytes)}"
                    + ("\nResumed an interrupted backup." if snapshot.resumed else ""),
                )
                self.repository_label.set("")
                self.repository_path.set(str(repository))
                self._start_repository_refresh()

            self._run_task(
                "Restarting backup..." if restart else "Preparing backup...",
                work,
                done,
            )

        launch(restart=False)

    def _selected_repository_snapshot(
        self, *, warn: bool = True
    ) -> repository_engine.SnapshotInfo | None:
        selection = self.repository_snapshot_tree.selection()
        if len(selection) != 1:
            if warn:
                messagebox.showwarning(
                    APP_NAME, "Select one snapshot from the Snapshots table first."
                )
            return None
        snapshot = self.repository_snapshots.get(selection[0])
        if snapshot is None and warn:
            messagebox.showwarning(
                APP_NAME, "Refresh the repository and select the snapshot again."
            )
        return snapshot

    def _repository_snapshot_selected(self, _event=None) -> None:
        snapshot = self._selected_repository_snapshot(warn=False)
        if snapshot is None:
            self.repository_pin_button.config(text="Pin selected")
        else:
            self.repository_pin_button.config(
                text="Unpin selected" if snapshot.pinned else "Pin selected"
            )

    def _show_repository_snapshots(self) -> None:
        self.repository_result_tabs.select(0)

    def _open_repository_search_snapshot(self, _event=None) -> None:
        selection = self.repository_history_tree.selection()
        if len(selection) != 1:
            return
        snapshot_id = self.repository_history_snapshot_ids.get(selection[0])
        if snapshot_id not in self.repository_snapshots:
            return
        self.repository_result_tabs.select(0)
        self.repository_snapshot_tree.selection_set(snapshot_id)
        self.repository_snapshot_tree.focus(snapshot_id)
        self.repository_snapshot_tree.see(snapshot_id)

    def _start_repository_search(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return
        query = self.repository_search.get().strip()
        if not query:
            messagebox.showwarning(
                APP_NAME, "Enter part of a filename, stored path, or snapshot label."
            )
            return

        def work():
            return repository_engine.search_history(
                repository, query, limit=1000
            )

        def done(results: list[repository_engine.HistoryEntry]) -> None:
            for item_id in self.repository_history_tree.get_children():
                self.repository_history_tree.delete(item_id)
            self.repository_history_snapshot_ids.clear()
            for index, result in enumerate(results):
                item_id = f"history-{index}"
                self.repository_history_snapshot_ids[item_id] = (
                    result.snapshot_id
                )
                self.repository_history_tree.insert(
                    "",
                    tk.END,
                    iid=item_id,
                    values=(
                        _format_time_ns(result.created_at_ns),
                        result.path,
                        result.kind.title(),
                        _format_size(result.size),
                        result.label or "(no label)",
                        result.snapshot_id[:10],
                    ),
                )
            self.repository_result_tabs.select(1)
            self.status_text.set(
                f"Found {len(results):,} path-history result(s)"
            )

        self._run_task("Searching backup history...", work, done)

    def _start_repository_restore(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return
        snapshot = self._selected_repository_snapshot()
        if snapshot is None:
            return
        parent_value = filedialog.askdirectory(
            title="Choose the parent folder for the restored snapshot"
        )
        if not parent_value:
            return
        source_name = Path(snapshot.source_path).name or "restored snapshot"
        created_name = dt.datetime.fromtimestamp(
            snapshot.created_at_ns / 1_000_000_000
        ).strftime("%Y-%m-%d %H%M")
        default_name = f"{source_name} restored {created_name}"
        folder_name = simpledialog.askstring(
            APP_NAME,
            "Name the new restored folder:",
            initialvalue=default_name,
            parent=self.root,
        )
        if folder_name is None:
            return
        folder_name = folder_name.strip()
        if (
            not folder_name
            or folder_name in {".", ".."}
            or Path(folder_name).name != folder_name
        ):
            messagebox.showwarning(APP_NAME, "Enter one safe folder name.")
            return
        destination = Path(parent_value).resolve() / folder_name
        if destination.exists():
            messagebox.showwarning(
                APP_NAME,
                "Verified restores never merge into an existing folder. Choose a "
                "different name.",
            )
            return
        snapshot_id = snapshot.snapshot_id

        def work():
            return repository_engine.restore_snapshot(
                repository, snapshot_id, destination
            )

        def done(result: repository_engine.RestoreResult) -> None:
            messagebox.showinfo(
                APP_NAME,
                f"Restored and verified {result.file_count:,} file(s).\n\n"
                f"{result.destination}",
            )

        self._run_task("Restoring and verifying snapshot...", work, done)

    def _start_repository_pin_toggle(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return
        snapshot = self._selected_repository_snapshot()
        if snapshot is None:
            return
        snapshot_id = snapshot.snapshot_id
        pinned = not snapshot.pinned

        def work():
            return repository_engine.pin_snapshot(
                repository, snapshot_id, pinned=pinned
            )

        def done(_snapshot: repository_engine.SnapshotInfo) -> None:
            self.repository_path.set(str(repository))
            self._start_repository_refresh()

        action = "Pinning" if pinned else "Unpinning"
        self._run_task(f"{action} snapshot...", work, done)

    def _start_repository_export(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return
        snapshot = self._selected_repository_snapshot()
        if snapshot is None:
            return
        created = dt.datetime.fromtimestamp(
            snapshot.created_at_ns / 1_000_000_000
        ).strftime("%Y-%m-%d")
        initial_name = (
            f"{Path(snapshot.source_path).name or 'snapshot'}-"
            f"{created}-{snapshot.snapshot_id[:8]}.gmw"
        )
        selected = filedialog.asksaveasfilename(
            title="Export snapshot as a portable GMW archive",
            initialfile=initial_name,
            defaultextension=".gmw",
            filetypes=ARCHIVE_TYPES,
        )
        if not selected:
            return
        output = Path(selected).resolve()
        if output.exists():
            messagebox.showwarning(
                APP_NAME,
                "Portable export will not replace an existing file. Choose a new name.",
            )
            return
        snapshot_id = snapshot.snapshot_id

        def work():
            return repository_engine.export_snapshot(
                repository,
                snapshot_id,
                output,
                profile="balanced",
            )

        def done(result: repository_engine.ExportResult) -> None:
            messagebox.showinfo(
                APP_NAME,
                "Portable GMW archive created.\n\n"
                f"Archive size: {_format_size(result.archive_bytes)}\n"
                f"Profile: {result.profile}\n\n"
                f"{result.output}",
            )

        self._run_task("Creating portable GMW archive...", work, done)

    def _start_repository_verify(self, *, full: bool) -> None:
        repository = self._checked_repository()
        if repository is None:
            return

        def work():
            return repository_engine.verify_repository(
                repository, full=full
            )

        def done(result: repository_engine.VerifyResult) -> None:
            verification = (
                "Full verification read and checked every stored object and file."
                if result.full_data_verified
                else "Quick verification checked repository structure and references."
            )
            messagebox.showinfo(
                APP_NAME,
                f"{verification}\n\n"
                f"Snapshots: {result.snapshot_count:,}\n"
                f"Files across history: {result.file_count:,}\n"
                f"Unique objects: {result.object_count:,}\n"
                f"Compressed object payload: "
                f"{_format_size(result.object_payload_bytes)}\n"
                f"Active pack files: {_format_size(result.pack_file_bytes)}\n"
                f"All repository files: "
                f"{_format_size(result.repository_file_bytes)}\n"
                f"Recoverable trash: {_format_size(result.trash_file_bytes)}\n"
                f"Unreferenced objects: {result.unreferenced_object_count:,}\n"
                f"Orphan packs: {result.orphan_pack_count:,}",
            )

        label = (
            "Fully verifying all repository data..."
            if full
            else "Quickly verifying repository structure..."
        )
        self._run_task(label, work, done)

    def _repository_retention_policy(
        self,
    ) -> repository_engine.RetentionPolicy | None:
        raw_values = (
            self.repository_keep_last.get().strip(),
            self.repository_keep_daily.get().strip(),
            self.repository_keep_weekly.get().strip(),
            self.repository_keep_monthly.get().strip(),
        )
        try:
            values = tuple(int(value) for value in raw_values)
            policy = repository_engine.RetentionPolicy(*values)
            policy.validate()
        except (ValueError, repository_engine.RepositoryError):
            messagebox.showwarning(
                APP_NAME,
                "Retention values must be whole numbers of zero or more.",
            )
            return None
        return policy

    def _start_repository_retention_preview(self) -> None:
        repository = self._checked_repository()
        if repository is None:
            return
        policy = self._repository_retention_policy()
        if policy is None:
            return

        def work():
            return repository_engine.plan_retention(repository, policy)

        def done(plan: repository_engine.RetentionPlan) -> None:
            if (
                not plan.remove_snapshot_ids
                and plan.fully_reclaimable_pack_bytes == 0
            ):
                messagebox.showinfo(
                    APP_NAME,
                    "Nothing is eligible for cleanup under this retention policy.\n\n"
                    f"Snapshots kept: {len(plan.keep_snapshot_ids):,}",
                )
                return
            apply_now = messagebox.askyesno(
                APP_NAME,
                "Retention preview\n\n"
                f"Snapshots kept: {len(plan.keep_snapshot_ids):,}\n"
                f"Snapshots moved to trash: {len(plan.remove_snapshot_ids):,}\n"
                f"Logical history removed: "
                f"{_format_size(plan.logical_bytes_removed)}\n"
                f"Pack data eligible for recoverable trash: "
                f"{_format_size(plan.fully_reclaimable_pack_bytes)}\n"
                f"Logical dead content sharing retained packs "
                f"(not currently disk-reclaimable): "
                f"{_format_size(plan.unreclaimed_dead_object_raw_bytes)}\n\n"
                "Apply this exact freshly previewed plan?\n"
                "Removed repository files are moved into its trash folder. "
                "Disk usage is retained until a future trash-purge stage.",
                icon=messagebox.WARNING,
            )
            if apply_now:
                self._start_repository_retention_apply(
                    repository, policy, plan.plan_id
                )

        self._run_task("Preparing retention preview...", work, done)

    def _start_repository_retention_apply(
        self,
        repository: Path,
        policy: repository_engine.RetentionPolicy,
        plan_id: str,
    ) -> None:
        def work():
            return repository_engine.prune_repository(
                repository,
                policy,
                apply=True,
                expected_plan_id=plan_id,
            )

        def done(result: repository_engine.PruneResult) -> None:
            location = (
                f"\n\nTrash: {result.trash_path}"
                if result.trash_path
                else ""
            )
            moved_pack_bytes = int(
                getattr(result, "moved_to_trash_pack_bytes", 0)
            )
            messagebox.showinfo(
                APP_NAME,
                "Retention cleanup applied.\n\n"
                f"Snapshots moved: {result.moved_manifest_count:,}\n"
                f"Packs moved: {result.moved_pack_count:,}\n"
                f"Pack data moved to recoverable trash: "
                f"{_format_size(moved_pack_bytes)}\n"
                "Disk usage is retained until a future trash-purge stage."
                f"{location}",
            )
            self.repository_path.set(str(repository))
            self._start_repository_refresh()

        self._run_task("Applying verified retention plan...", work, done)

    def _start_load_data_sources(self) -> None:
        archive = self._checked_data_archive()
        if archive is None:
            return

        def work():
            return gmw_tool.list_structured_sources(archive)

        def done(sources) -> None:
            self.data_source_map.clear()
            labels: list[str] = []
            for source in sources:
                label = (
                    f"{source.path}  —  {source.row_count:,} rows × "
                    f"{source.column_count:,} columns"
                )
                self.data_source_map[label] = source
                labels.append(label)
            self.data_source_box.configure(values=labels)
            total_rows = sum(source.row_count for source in sources)
            self.data_catalog_note.set(
                f"{len(sources):,} table(s), {total_rows:,} queryable row(s)"
            )
            if not labels:
                self.data_source_label.set("")
                self.data_result_count.set(
                    "No structured tables — create a new 5.1 Vault containing CSV, JSON, or similar data"
                )
                self._render_data_result(None)
                return
            self.data_source_label.set(labels[0])
            self._data_source_changed()

        self._run_task("Loading structured table catalog...", work, done)

    def _selected_data_source(self):
        return self.data_source_map.get(self.data_source_label.get())

    def _data_source_changed(self, _event=None) -> None:
        archive = self._checked_data_archive()
        source = self._selected_data_source()
        if archive is None or source is None:
            return

        def work():
            return gmw_tool.list_structured_columns(archive, source.id)

        def done(columns) -> None:
            self.data_column_map = {"All columns": ""}
            self.data_sort_map = {"Original row order": ""}
            for item in columns:
                label = f"{item.source_name}  [{item.declared_type}]"
                if label in self.data_column_map:
                    label = f"{label}  ({item.column_name})"
                self.data_column_map[label] = item.column_name
                self.data_sort_map[label] = item.column_name
            self.data_column_box.configure(values=tuple(self.data_column_map))
            self.data_sort_box.configure(values=tuple(self.data_sort_map))
            self.data_column_label.set("All columns")
            self.data_sort_label.set("Original row order")
            self.data_sql.delete("1.0", tk.END)
            self.data_sql.insert(
                "1.0", f'SELECT * FROM "{source.table_name}" LIMIT 1000;'
            )
            self._start_data_query()

        self._run_task("Loading table schema...", work, done)

    def _render_data_result(self, result) -> None:
        for item_id in self.data_results.get_children():
            self.data_results.delete(item_id)
        if result is None:
            self.data_results.configure(columns=())
            self.data_current_result = None
            return
        columns = tuple(result.columns)
        self.data_results.configure(columns=columns, displaycolumns=columns)
        for index, column in enumerate(columns):
            label = "Row" if column == "__row__" else column
            self.data_results.heading(column, text=label)
            self.data_results.column(
                column,
                width=70 if index == 0 and column == "__row__" else 145,
                minwidth=55,
                stretch=False,
                anchor=tk.E if column == "__row__" else tk.W,
            )
        for row in result.rows:
            values = tuple("" if value is None else value for value in row)
            self.data_results.insert("", tk.END, values=values)
        self.data_current_result = result
        limited = " (more rows available)" if result.truncated else ""
        self.data_result_count.set(f"{len(result.rows):,} result row(s){limited}")

    def _start_data_query(self) -> None:
        archive = self._checked_data_archive()
        source = self._selected_data_source()
        if archive is None or source is None:
            return
        column = self.data_column_map.get(self.data_column_label.get(), "")
        sort_by = self.data_sort_map.get(self.data_sort_label.get(), "")

        def work():
            return gmw_tool.query_structured_source(
                archive,
                source.id,
                search=self.data_search.get().strip(),
                column=column,
                sort_by=sort_by,
                descending=self.data_descending.get(),
                limit=5000,
            )

        def done(result) -> None:
            self._render_data_result(result)
            self.status_text.set("Structured query complete")

        self._run_task("Querying structured rows...", work, done)

    def _start_sql_query(self) -> None:
        archive = self._checked_data_archive()
        if archive is None:
            return
        sql = self.data_sql.get("1.0", tk.END).strip()
        if not sql:
            messagebox.showwarning(APP_NAME, "Enter a SELECT query first.")
            return

        def work():
            return gmw_tool.execute_structured_sql(archive, sql, limit=5000)

        def done(result) -> None:
            self._render_data_result(result)
            self.status_text.set("SQL query complete")

        self._run_task("Running read-only SQL...", work, done)

    def _start_data_export(self) -> None:
        result = self.data_current_result
        if result is None:
            messagebox.showwarning(APP_NAME, "Run a structured-data query before exporting.")
            return
        source = self._selected_data_source()
        default_name = f"{source.name}-results.csv" if source is not None else "query-results.csv"
        selected = filedialog.asksaveasfilename(
            title="Export query results",
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[
                ("CSV table", "*.csv"),
                ("JSON records", "*.json"),
                ("TSV table", "*.tsv"),
            ],
        )
        if not selected:
            return
        output = Path(selected)
        if output.exists() and not messagebox.askyesno(
            APP_NAME, f"Replace this result file?\n\n{output}"
        ):
            return

        def work():
            gmw_tool.export_structured_result(result, output)
            return output

        def done(saved: Path) -> None:
            messagebox.showinfo(
                APP_NAME, f"Exported {len(result.rows):,} query result row(s).\n\n{saved}"
            )

        self._run_task("Exporting query results...", work, done)

    def _show_all_vault(self) -> None:
        self.vault_query.set("")
        self._start_vault_search()

    def _start_vault_search(self) -> None:
        archive = Path(self.vault_archive.get().strip())
        if not self.vault_archive.get().strip() or not archive.is_file():
            messagebox.showwarning(APP_NAME, "Choose an existing queryable Vault first.")
            return
        if not gmw_tool.is_vault_archive(archive):
            messagebox.showwarning(
                APP_NAME,
                "This is a normal archive, not a queryable Vault. Create or choose a Vault first.",
            )
            return
        query = self.vault_query.get().strip()
        extension = self.vault_extension.get().strip()

        def work():
            return gmw_tool.search_vault(
                archive, query, extension=extension, limit=1000
            )

        def done(results) -> None:
            for item_id in self.vault_results.get_children():
                self.vault_results.delete(item_id)
            for result in results:
                self.vault_results.insert(
                    "",
                    tk.END,
                    iid=str(result.id),
                    values=(
                        result.path,
                        result.media_type,
                        _format_size(result.size),
                        "Yes" if result.indexed else "No",
                    ),
                )
            self.vault_result_count.set(f"{len(results):,} result(s)")
            self.status_text.set("Vault search complete")

        self._run_task("Searching Vault...", work, done)

    def _selected_vault_paths(self) -> list[str]:
        paths: list[str] = []
        for item_id in self.vault_results.selection():
            values = self.vault_results.item(item_id, "values")
            if values:
                paths.append(str(values[0]))
        return paths

    def _start_vault_preview(self) -> None:
        paths = self._selected_vault_paths()
        if len(paths) != 1:
            messagebox.showwarning(APP_NAME, "Select one Vault result to preview.")
            return
        archive = Path(self.vault_archive.get().strip())
        stored_path = paths[0]

        def work():
            return gmw_tool.preview_vault_file(archive, stored_path)

        def done(text: str) -> None:
            self.vault_preview.config(state=tk.NORMAL)
            self.vault_preview.delete("1.0", tk.END)
            self.vault_preview.insert("1.0", text)
            self.vault_preview.config(state=tk.DISABLED)
            self.status_text.set(f"Previewing {stored_path}")

        self._run_task("Loading preview...", work, done)

    def _start_vault_extract_selected(self) -> None:
        paths = self._selected_vault_paths()
        if not paths:
            messagebox.showwarning(APP_NAME, "Select one or more Vault results to export.")
            return
        selected = filedialog.askdirectory(title="Choose where to export the selected files")
        if not selected:
            return
        destination = Path(selected)
        if destination.is_dir() and any(destination.iterdir()) and not messagebox.askyesno(
            APP_NAME,
            "The destination is not empty. Matching selected files will be replaced. Continue?",
        ):
            return
        archive = Path(self.vault_archive.get().strip())

        def work():
            return gmw_tool.extract_vault_files(archive, destination, paths)

        def done(_metadata: gmw_tool.Metadata) -> None:
            messagebox.showinfo(
                APP_NAME,
                f"Exported {len(paths):,} selected file(s).\n\n{destination}",
            )

        self._run_task("Exporting selected Vault files...", work, done)

    def _start_create(self) -> None:
        source = Path(self.source_folder.get().strip())
        output = Path(self.create_archive.get().strip())
        if not self.source_folder.get().strip() or not source.is_dir():
            messagebox.showwarning(APP_NAME, "Choose an existing source folder first.")
            return
        if not self.create_archive.get().strip():
            messagebox.showwarning(APP_NAME, "Choose where to save the archive.")
            return
        if output.exists() and not messagebox.askyesno(
            APP_NAME, f"Replace the existing archive?\n\n{output}"
        ):
            return
        profile = PROFILE_OPTIONS[self.profile_label.get()]

        def work():
            return gmw_tool.compress_folder(source, output, profile=profile)

        def done(meta: gmw_tool.Metadata) -> None:
            archive_size = output.stat().st_size
            saved = 0.0 if not meta.total_bytes else (1 - archive_size / meta.total_bytes) * 100
            if meta.format == "GMW-VAULT-1":
                messagebox.showinfo(
                    APP_NAME,
                    "Queryable Vault created successfully.\n\n"
                    f"Files: {meta.file_count:,}\n"
                    f"Original size: {_format_size(meta.total_bytes)}\n"
                    f"Vault size: {_format_size(archive_size)}\n"
                    f"Text files indexed: {meta.indexed_file_count:,}\n"
                    f"Data tables: {meta.structured_source_count:,}\n"
                    f"Queryable rows: {meta.structured_row_count:,}\n"
                    f"Unique compressed objects: {meta.object_count:,}\n"
                    f"Exact duplicate files: {meta.duplicate_file_count:,}\n"
                    f"Duplicate data reused: {_format_size(meta.deduplicated_bytes)}\n\n"
                    "Open Search Vault for files or Data Tables for rows and columns.\n\n"
                    f"{output}",
                )
                return
            media_note = ""
            if saved < 10:
                media_note = (
                    "\n\nThis folder appears to contain mostly files that are already compressed "
                    "(such as PNG, MP4, ZIP, or MP3), so further lossless reduction is limited."
                )
            duplicate_note = ""
            if meta.duplicate_file_count:
                duplicate_note = (
                    f"\nExact duplicates stored once: {meta.duplicate_file_count:,}"
                )
            messagebox.showinfo(
                APP_NAME,
                "Archive created successfully.\n\n"
                f"Files: {meta.file_count:,}\n"
                f"Original size: {_format_size(meta.total_bytes)}\n"
                f"Archive size: {_format_size(archive_size)}\n"
                f"Space saved: {saved:.1f}%"
                f"{duplicate_note}"
                f"{media_note}\n\n{output}",
            )

        self._run_task("Creating archive...", work, done)

    def _start_extract(self) -> None:
        archive = Path(self.extract_archive.get().strip())
        destination = Path(self.extract_folder.get().strip())
        if not self.extract_archive.get().strip() or not archive.is_file():
            messagebox.showwarning(APP_NAME, "Choose an existing GMW archive first.")
            return
        if not self.extract_folder.get().strip():
            messagebox.showwarning(APP_NAME, "Choose an extraction destination.")
            return
        if destination.is_dir() and any(destination.iterdir()) and not messagebox.askyesno(
            APP_NAME,
            "The destination is not empty. Files with matching names will be replaced. Continue?",
        ):
            return

        def work():
            return gmw_tool.extract_archive(archive, destination)

        def done(meta: gmw_tool.Metadata) -> None:
            messagebox.showinfo(
                APP_NAME,
                f"Extracted {meta.file_count:,} files successfully.\n\n{destination}",
            )

        self._run_task("Extracting files...", work, done)

    def _load_details(self) -> None:
        archive = Path(self.inspect_archive.get().strip())
        if not self.inspect_archive.get().strip() or not archive.is_file():
            messagebox.showwarning(APP_NAME, "Choose an existing GMW archive first.")
            return
        try:
            meta = gmw_tool.read_metadata(archive)
            archive_size = archive.stat().st_size
            created = dt.datetime.fromtimestamp(meta.created_at).strftime("%d %b %Y, %H:%M:%S")
            saved = 0.0 if not meta.total_bytes else (1 - archive_size / meta.total_bytes) * 100
            level = "" if meta.compression_level is None else f" level {meta.compression_level}"
            layout = (
                f"Chunk size    {_format_size(meta.chunk_size)}\n" if meta.chunk_size else ""
            )
            dedup = (
                f"Duplicates    {meta.duplicate_file_count:,} files stored once\n"
                if meta.whole_file_dedup
                else ""
            )
            vault_details = ""
            if meta.format == "GMW-VAULT-1":
                vault_details = (
                    f"Schema        {meta.schema_version}\n"
                    f"Objects       {meta.object_count:,}\n"
                    f"Text indexed  {meta.indexed_file_count:,} files\n"
                    f"Data tables   {meta.structured_source_count:,}\n"
                    f"Table rows    {meta.structured_row_count:,}\n"
                    f"Duplicates    {meta.duplicate_file_count:,} files\n"
                    f"Data reused   {_format_size(meta.deduplicated_bytes)}\n"
                )
            text = (
                f"Archive       {archive.name}\n"
                f"Format        {meta.format}\n"
                f"Files         {meta.file_count:,}\n"
                f"Original      {_format_size(meta.total_bytes)}\n"
                f"Archive size  {_format_size(archive_size)}\n"
                f"Space saved   {saved:.1f}%\n"
                f"Compression   {meta.compressor}{level}\n"
                f"Profile       {meta.profile}\n"
                f"{dedup}"
                f"{vault_details}"
                f"{layout}"
                f"Created       {created}\n"
                f"Build time    {meta.elapsed_seconds:.2f} seconds\n"
            )
            self.details.config(state=tk.NORMAL)
            self.details.delete("1.0", tk.END)
            self.details.insert("1.0", text)
            self.details.config(state=tk.DISABLED)
            self.status_text.set("Archive details loaded")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not read this archive.\n\n{exc}")

    def _start_export(self) -> None:
        archive = Path(self.inspect_archive.get().strip())
        if not self.inspect_archive.get().strip() or not archive.is_file():
            messagebox.showwarning(APP_NAME, "Choose an existing GMW archive first.")
            return
        selected = filedialog.asksaveasfilename(
            title="Export a standard ZIP file",
            initialdir=str(archive.parent),
            initialfile=f"{archive.stem}.zip",
            defaultextension=".zip",
            filetypes=[("ZIP archives", "*.zip")],
        )
        if not selected:
            return
        output = Path(selected)
        if output.exists() and not messagebox.askyesno(APP_NAME, f"Replace this ZIP file?\n\n{output}"):
            return

        def work():
            return gmw_tool.export_zip(archive, output)

        def done(meta: gmw_tool.Metadata) -> None:
            messagebox.showinfo(
                APP_NAME,
                f"Exported {meta.file_count:,} files to a standard ZIP archive.\n\n{output}",
            )

        self._run_task("Exporting ZIP...", work, done)

    def _run_task(self, label: str, work: Callable[[], object], done: Callable[[object], None]) -> None:
        if self.busy:
            return
        self.busy = True
        self.status_text.set(label)
        self.progress.start(12)
        self._saved_action_states = {
            button: str(button.cget("state"))
            for button in self.action_buttons
        }
        for button in self.action_buttons:
            button.config(state=tk.DISABLED)

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda: self._finish_task(None, done, error))
            else:
                self.root.after(0, lambda: self._finish_task(result, done, None))

        threading.Thread(target=runner, name="rat-trap-worker", daemon=True).start()

    def _finish_task(
        self, result: object | None, done: Callable[[object], None], error: str | None
    ) -> None:
        self.progress.stop()
        for button in self.action_buttons:
            button.config(
                state=self._saved_action_states.get(button, tk.NORMAL)
            )
        self._saved_action_states.clear()
        self.busy = False
        if error is not None:
            self.status_text.set("Operation failed")
            messagebox.showerror(APP_NAME, f"The operation could not be completed.\n\n{error}")
            return
        self.status_text.set("Ready")
        done(result)


def main() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    if "--self-test" in sys.argv:
        _self_test()
        return
    if "--self-test-folder" in sys.argv:
        index = sys.argv.index("--self-test-folder")
        try:
            source = Path(sys.argv[index + 1])
        except IndexError as exc:
            raise RuntimeError("--self-test-folder requires a folder path") from exc
        _folder_self_test(source)
        return
    root = tk.Tk()
    RatTrapApp(root)
    root.mainloop()


def _require_fastcdc_accelerator() -> None:
    """Fail the release gate if the frozen build lost its native chunker."""
    if not repository_engine.FastCDC.__module__.startswith("pyfastcdc.cy"):
        raise RuntimeError(
            "Packaged FastCDC Cython accelerator is unavailable"
        )


def _self_test() -> None:
    """Exercise the frozen GUI and Zstandard archive engine without showing a window."""
    _require_fastcdc_accelerator()
    root = tk.Tk()
    root.withdraw()
    app = RatTrapApp(root)
    root.update_idletasks()
    if app.tabs.index("end") != 6:
        raise RuntimeError("GUI did not create all expected tabs")
    root.destroy()

    with tempfile.TemporaryDirectory(prefix="rat-trap-self-test-") as temporary:
        base = Path(temporary)
        source = base / "source"
        source.mkdir()
        expected = ("Rat-Trap packaged self-test\n" * 1024).encode("utf-8")
        (source / "sample.txt").write_bytes(expected)
        (source / "people.csv").write_text(
            "name,age\nAlice,31\nBob,27\n", encoding="utf-8"
        )
        archive = base / "sample.gmw"
        restored = base / "restored"
        gmw_tool.compress_folder(source, archive, compressor="zstd")
        gmw_tool.extract_archive(archive, restored)
        if (restored / "sample.txt").read_bytes() != expected:
            raise RuntimeError("Packaged archive round-trip did not preserve file contents")
        repository = base / "repository"
        repository_restored = base / "repository-restored"
        repository_engine.init_repository(repository)
        snapshot = repository_engine.create_snapshot(
            repository, source, label="Packaged self-test"
        )
        repository_engine.restore_snapshot(
            repository, snapshot.snapshot_id, repository_restored
        )
        verified_repository = repository_engine.verify_repository(
            repository, full=True
        )
        if (
            verified_repository.snapshot_count != 1
            or (repository_restored / "sample.txt").read_bytes() != expected
        ):
            raise RuntimeError(
                "Packaged repository round-trip did not preserve file contents"
            )
        vault = base / "sample.vault.gmw"
        vault_restored = base / "vault-restored"
        gmw_tool.compress_folder(source, vault, profile="vault")
        results = gmw_tool.search_vault(vault, "packaged self-test")
        if [result.path for result in results] != ["sample.txt"]:
            raise RuntimeError("Packaged Vault search failed")
        tables = gmw_tool.list_structured_sources(vault)
        if len(tables) != 1 or tables[0].path != "people.csv":
            raise RuntimeError("Packaged structured-data catalog failed")
        rows = gmw_tool.query_structured_source(vault, tables[0].id, search="Alice")
        if len(rows.rows) != 1 or rows.rows[0][1] != "Alice":
            raise RuntimeError("Packaged structured-data query failed")
        gmw_tool.extract_archive(vault, vault_restored)
        if (vault_restored / "sample.txt").read_bytes() != expected:
            raise RuntimeError("Packaged Vault round-trip did not preserve file contents")


def _tree_digest(folder: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total_bytes = 0
    file_count = 0
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        relative = path.relative_to(folder).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        with open(path, "rb") as fp:
            while True:
                block = fp.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                total_bytes += len(block)
        file_count += 1
    return digest.hexdigest(), total_bytes, file_count


def _folder_self_test(source: Path) -> None:
    """Release-only check: run every packaged profile against a real folder."""
    _require_fastcdc_accelerator()
    source = source.resolve()
    if not source.is_dir():
        raise RuntimeError(f"Self-test folder not found: {source}")
    expected = _tree_digest(source)
    with tempfile.TemporaryDirectory(prefix="rat-trap-frozen-test-") as temporary:
        root = Path(temporary)
        for profile in ("fast", "balanced", "smallest", "vault"):
            archive = root / f"{profile}.gmw"
            restored = root / f"{profile}-restored"
            gmw_tool.compress_folder(source, archive, profile=profile)
            metadata = gmw_tool.read_metadata(archive)
            if metadata.profile != profile:
                raise RuntimeError(f"Packaged {profile} metadata is incorrect")
            gmw_tool.extract_archive(archive, restored)
            if _tree_digest(restored) != expected:
                raise RuntimeError(f"Packaged {profile} round-trip failed")
        repository = root / "repository"
        repository_restored = root / "repository-restored"
        repository_engine.init_repository(repository)
        snapshot = repository_engine.create_snapshot(
            repository, source, label="Packaged folder gate"
        )
        repository_engine.restore_snapshot(
            repository, snapshot.snapshot_id, repository_restored
        )
        verified = repository_engine.verify_repository(repository, full=True)
        if (
            verified.snapshot_count != 1
            or _tree_digest(repository_restored) != expected
        ):
            raise RuntimeError("Packaged repository folder round-trip failed")


if __name__ == "__main__":
    main()
