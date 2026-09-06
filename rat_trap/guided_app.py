"""Guided tutorials on the real desktop controls, with sample-only operations."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import archive_tutorials, desktop_app, desktop_preview2, diagnostics, history_tutorials, protection_tutorials, tutorials, windows_app


SUPPORT_VERSION = "5.7.0-desktop-preview.2-tutorial.4"


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


class GuidedRatTrapApp(desktop_preview2.DesktopPreview2App):
    def __init__(self, root, *, diagnostic_log=None):
        self.tutorial_active = False
        self.tutorial_id = "vault-search"
        self.tutorial_session_token = None
        self.tutorial_demo = None
        self.tutorial_target = None
        self._tutorial_index = 0
        self._tutorial_pending_action = None
        self._tutorial_worker_kind = None
        self._tutorial_next_step = None
        self._tutorial_snapshot = None
        self._tutorial_widget_states = {}
        self._tutorial_bindtags = {}
        self._tutorial_gate_commands = []
        self._tutorial_outline_after = None
        self._tutorial_focus_after = None
        self._tutorial_recovery_after = None
        self._tutorial_internal_navigation = False
        self._tutorial_catalog = None
        self._tutorial_error = ""
        self._lesson_profile_used = None
        self._lesson_verification = None
        self._protection_key_selected = False
        self._protection_verification = None
        self._history_verification = None
        self._coach_tag = f"RatTrapTutorial_{id(self)}"
        super().__init__(root, diagnostic_log=diagnostic_log)

    @property
    def tutorial_step(self):
        return self._tutorial_steps[self._tutorial_index].id if self.tutorial_active else ""

    @property
    def _tutorial_steps(self):
        return tutorials.STEPS_BY_ID[self.tutorial_id]

    @property
    def _tutorial_workspace(self):
        return {"vault-search": "Search Vault", "compress": "Create archive", "restore": "Extract archive", "protect": "Secure files", "history": "Backups & history"}[self.tutorial_id]

    def _build_ui(self):
        super()._build_ui()
        self.root.title("Rat-Trap — Desktop Preview 2 · Guided tutorials")
        top = self.tabs.master.winfo_children()[0]
        self.tutorial_button = ttk.Button(top, text="Show me how…", command=self.show_tutorials)
        self.tutorial_button.pack(side="right", padx=(0, 8))
        self.action_buttons.append(self.tutorial_button)
        self.vault_browse_button = next(w for w in self.pages["Search Vault"].grid_slaves(row=2, column=2) if isinstance(w, ttk.Button))
        self.vault_search_button = next(w for w in _descendants(self.pages["Search Vault"]) if isinstance(w, ttk.Button) and w.cget("text") == "Search")
        self.vault_preview_button = next(w for w in _descendants(self.pages["Search Vault"]) if isinstance(w, ttk.Button) and w.cget("text") == "Preview selected")
        self._build_archive_lesson_controls()
        self._build_protection_lesson_controls()
        self._build_history_lesson_controls()
        self._normal_workspace_select = self.tabs.select
        self.tabs.select = self._guard_workspace_select
        self._normal_secure_select = self.secure_modes.select
        self.secure_modes.select = self._guard_secure_select
        self._normal_repository_select = self.repository_result_tabs.select
        self.repository_result_tabs.select = self._guard_repository_select
        self._build_coach()
        self.vault_query.trace_add("write", self._tutorial_input_changed)
        self.profile_label.trace_add("write", self._tutorial_input_changed)
        self.protection_password_ack.trace_add("write", self._tutorial_input_changed)
        self.vault_results.bind("<<TreeviewSelect>>", self._tutorial_input_changed, add="+")
        self.repository_snapshot_tree.bind("<<TreeviewSelect>>", self._tutorial_input_changed, add="+")
        self.root.bind("<Escape>", self._tutorial_escape, add="+")
        self.root.bind("<Configure>", self._tutorial_window_changed, add="+")
        # Keep the outline attached when a user drags a workspace scrollbar,
        # not only when a root resize or mouse-wheel event occurs.
        for canvas in (self._sidebar_canvas, *(page.canvas for page in self.page_scrollers.values())):
            for option in ("xscrollcommand", "yscrollcommand"):
                command = canvas.cget(option)
                def scrolled(*values, command=command):
                    if command:
                        self.root.tk.call(*self.root.tk.splitlist(command), *values)
                    self._queue_tutorial_outline()
                canvas.configure(**{option: scrolled})

    def _build_archive_lesson_controls(self):
        create, restore = self.pages["Create archive"], self.pages["Extract archive"]
        def button(page, row):
            return next(w for w in page.grid_slaves(row=row, column=2) if isinstance(w, ttk.Button))
        self.lesson_source_button = button(create, 2)
        self.lesson_output_button = button(create, 3)
        self.lesson_archive_button = button(restore, 2)
        self.lesson_destination_button = button(restore, 3)
        self.lesson_profile_box = next(w for w in create.grid_slaves(row=4, column=1) if isinstance(w, ttk.Combobox))
        self.lesson_create_button = next(w for w in _descendants(create) if isinstance(w, ttk.Button) and w.cget("text") == "Create")
        self.lesson_extract_button = next(w for w in _descendants(restore) if isinstance(w, ttk.Button) and w.cget("text") == "Extract files")
        self._lesson_frames = {}
        for key, page, row in (("compress", create, 10), ("restore", restore, 5)):
            frame = ttk.Frame(page, padding=(0, 12))
            frame.grid(row=row, column=0, columnspan=3, sticky="ew")
            frame.columnconfigure(0, weight=1)
            ttk.Label(frame, text="Practice result", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
            if key == "restore":
                self.lesson_verify_button = ttk.Button(frame, text="Check restored files", command=self._verify_practice_restore)
                self.lesson_verify_button.grid(row=1, column=0, sticky="w", pady=8)
                self.action_buttons.append(self.lesson_verify_button)
            result = tk.Text(frame, height=7, width=1, wrap="word", state="disabled", relief="flat", background="#F1F8F5", font=("Segoe UI", 10), padx=10, pady=8)
            result.grid(row=2, column=0, sticky="ew")
            result_scrollbar = ttk.Scrollbar(frame, orient="vertical", command=result.yview)
            result_scrollbar.grid(row=2, column=1, sticky="ns")
            result.configure(yscrollcommand=result_scrollbar.set)
            setattr(self, "create_lesson_result" if key == "compress" else "restore_lesson_result", result)
            self._lesson_frames[key] = frame
            frame.grid_remove()

    def _build_protection_lesson_controls(self):
        protect, restore = self.secure_protect_mode, self.secure_restore_mode
        def button(page, row):
            return next(w for w in page.grid_slaves(row=row, column=2) if isinstance(w, ttk.Button))
        self.protection_source_button = button(protect, 2)
        self.protection_output_button = button(protect, 3)
        self.protection_restore_source_button = button(restore, 2)
        self.protection_restore_destination_button = button(restore, 3)
        self.protection_seal_button = next(w for w in _descendants(protect) if isinstance(w, ttk.Button) and w.cget("text") == "Protect file")
        self.protection_restore_button = next(w for w in _descendants(restore) if isinstance(w, ttk.Button) and w.cget("text") == "Restore plaintext copy")
        self.protection_password_ack = tk.BooleanVar(value=False)
        self._protection_frames = []
        for page, restoring in ((protect, False), (restore, True)):
            frame = ttk.Frame(page, padding=(0, 12))
            frame.grid(row=5, column=0, columnspan=3, sticky="ew")
            frame.columnconfigure(0, weight=1)
            ttk.Label(frame, text="Fictional security practice", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
            if restoring:
                self.protection_recovery_button = ttk.Button(frame, text="Recover sample without password", command=self._recover_practice_file)
                self.protection_recovery_button.grid(row=1, column=0, sticky="w", pady=6)
                self.protection_verify_button = ttk.Button(frame, text="Check both recovered files", command=self._verify_practice_protection)
                self.protection_verify_button.grid(row=2, column=0, sticky="w", pady=6)
                self.action_buttons.extend((self.protection_recovery_button, self.protection_verify_button))
            else:
                self.protection_password_check = ttk.Checkbutton(frame, text="Use a disposable practice password", variable=self.protection_password_ack)
                self.protection_password_check.grid(row=1, column=0, sticky="w", pady=6)
                self.protection_key_button = ttk.Button(frame, text="Use separate practice key folder", command=self._select_practice_key)
                self.protection_key_button.grid(row=2, column=0, sticky="w", pady=6)
                self.action_buttons.append(self.protection_key_button)
            result = tk.Text(frame, height=7, width=1, wrap="word", state="disabled", relief="flat", background="#F1F8F5", font=("Segoe UI", 10), padx=10, pady=8)
            result.grid(row=3, column=0, sticky="ew")
            scroll = ttk.Scrollbar(frame, orient="vertical", command=result.yview)
            scroll.grid(row=3, column=1, sticky="ns")
            result.configure(yscrollcommand=scroll.set)
            setattr(self, "protection_restore_result" if restoring else "protection_result", result)
            self._protection_frames.append(frame)
            frame.grid_remove()

    def _build_history_lesson_controls(self):
        page = self.pages["Backups & history"]
        def button(row):
            return next(w for w in page.grid_slaves(row=row, column=2) if isinstance(w, ttk.Button))
        self.history_source_button = button(4)
        self.history_repository_button = button(2)
        self.history_backup_button = button(5)
        self.history_refresh_button = next(w for w in _descendants(page) if isinstance(w, ttk.Button) and w.cget("text") == "Open / refresh")
        self.history_restore_button = next(w for w in _descendants(page) if isinstance(w, ttk.Button) and w.cget("text") == "Restore selected...")
        self.history_restore_destination = tk.StringVar()
        self._history_tree_style = f"HistoryPractice{id(self)}.Treeview"
        style = ttk.Style(self.root)
        style.configure(self._history_tree_style, font=("Segoe UI", 9), rowheight=max(24, int(22 * self.scale)))
        style.configure(self._history_tree_style + ".Heading", font=("Segoe UI", 9, "bold"), padding=4)
        frame = ttk.Frame(page, padding=(0, 12))
        frame.grid(row=11, column=0, columnspan=3, sticky="ew")
        frame.columnconfigure(0, weight=1)
        self._history_frame = frame
        ttk.Label(frame, text="Practice backup history", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        self.history_change_button = ttk.Button(frame, text="Change the sample file", command=self._change_history_sample)
        self.history_change_button.grid(row=1, column=0, sticky="w", pady=6)
        self.history_destination_button = ttk.Button(frame, text="Use separate restore folder", command=self._select_history_destination)
        self.history_destination_button.grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.history_restore_destination, state="readonly", width=1).grid(row=3, column=0, sticky="ew", pady=4)
        self.history_verify_button = ttk.Button(frame, text="Check the older files", command=self._verify_history_restore)
        self.history_verify_button.grid(row=4, column=0, sticky="w", pady=6)
        self.history_result = tk.Text(frame, height=7, width=1, wrap="word", state="disabled", relief="flat", background="#F1F8F5", font=("Segoe UI", 10), padx=10, pady=8)
        self.history_result.grid(row=5, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.history_result.yview)
        scrollbar.grid(row=5, column=1, sticky="ns")
        self.history_result.configure(yscrollcommand=scrollbar.set)
        self.action_buttons.extend((self.history_change_button, self.history_destination_button, self.history_verify_button))
        frame.grid_remove()

    def _write_history_result(self, text):
        self.history_result.configure(state="normal")
        self.history_result.delete("1.0", "end")
        self.history_result.insert("1.0", text)
        self.history_result.configure(state="disabled")

    def _guard_repository_select(self, tab_id=None):
        if tab_id is not None and self.tutorial_active:
            return self._normal_repository_select()
        return self._normal_repository_select(tab_id)

    def _select_repository_mode(self, mode):
        disabled = self.repository_result_tabs.instate(["disabled"])
        self.repository_result_tabs.state(["!disabled"])
        try:
            self._normal_repository_select(mode)
        finally:
            if disabled:
                self.repository_result_tabs.state(["disabled"])

    def _show_repository_snapshots(self):
        if not self.tutorial_active:
            return super()._show_repository_snapshots()

    def _open_repository_search_snapshot(self, event=None):
        if not self.tutorial_active:
            return super()._open_repository_search_snapshot(event)

    def _repository_snapshot_selected(self, event=None):
        if not self.tutorial_active:
            return super()._repository_snapshot_selected(event)
        self._tutorial_input_changed()

    def _write_protection_result(self, text, *, restoring=False):
        target = self.protection_restore_result if restoring else self.protection_result
        target.configure(state="normal")
        target.delete("1.0", "end")
        target.insert("1.0", text)
        target.configure(state="disabled")

    def _guard_secure_select(self, tab_id=None):
        if tab_id is not None and self.tutorial_active:
            return self._normal_secure_select()
        return self._normal_secure_select(tab_id)

    def _show_protection_step(self):
        if self.tutorial_id == "protect":
            protecting = self.tutorial_step in {"navigate", "load", "destination", "password", "key", "seal", "open"}
            self._select_protection_mode(self.secure_protect_mode if protecting else self.secure_restore_mode)

    def _select_protection_mode(self, mode):
        # ttk refuses programmatic tab changes while the notebook is disabled.
        # The input gate remains active throughout this internal selection.
        disabled = self.secure_modes.instate(["disabled"])
        self.secure_modes.state(["!disabled"])
        try:
            self._normal_secure_select(mode)
        finally:
            if disabled:
                self.secure_modes.state(["disabled"])

    def _write_lesson_result(self, text):
        target = self.create_lesson_result if self.tutorial_id == "compress" else self.restore_lesson_result
        target.configure(state="normal")
        target.delete("1.0", "end")
        target.insert("1.0", text)
        target.configure(state="disabled")

    def _build_coach(self):
        self.tutorial_bubble = tk.Frame(self.tabs.master, background="#D6EEE7", padx=2, pady=2)
        arrow = tk.Canvas(self.tutorial_bubble, height=10, background="#D6EEE7", highlightthickness=0)
        arrow.pack(fill="x")
        arrow.create_polygon(20, 10, 29, 0, 38, 10, fill="#FFFFFF", outline="#FFFFFF")
        body = ttk.Frame(self.tutorial_bubble, padding=(14, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.tutorial_heading = tk.StringVar()
        self.tutorial_where = tk.StringVar()
        self.tutorial_action = tk.StringVar()
        self.tutorial_why = tk.StringVar()
        self.tutorial_expect = tk.StringVar()
        self.tutorial_feedback = tk.StringVar()
        ttk.Label(body, textvariable=self.tutorial_heading, style="Eyebrow.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        explanation = ttk.Frame(body)
        explanation.grid(row=1, column=0, columnspan=2, sticky="ew")
        explanation.columnconfigure(0, weight=1)
        self._coach_canvas = tk.Canvas(explanation, height=120, background="white", highlightthickness=0)
        self._coach_canvas.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(explanation, orient="vertical", command=self._coach_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._coach_canvas.configure(yscrollcommand=scrollbar.set)
        self._coach_copy = ttk.Frame(self._coach_canvas)
        self._coach_copy.columnconfigure(1, weight=1)
        self._coach_copy_item = self._coach_canvas.create_window(0, 0, window=self._coach_copy, anchor="nw")
        self._coach_labels = []
        self._coach_keys = []
        for row, (name, variable) in enumerate((("YOU ARE HERE", self.tutorial_where), ("DO THIS", self.tutorial_action), ("WHY", self.tutorial_why), ("EXPECT", self.tutorial_expect)), 1):
            key = ttk.Label(self._coach_copy, text=name, font=("Segoe UI", 8, "bold"), foreground="#176653")
            key.grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=2)
            self._coach_keys.append(key)
            label = ttk.Label(self._coach_copy, textvariable=variable, wraplength=700, font=("Segoe UI", 9))
            label.grid(row=row, column=1, sticky="nw", pady=2)
            self._coach_labels.append(label)
        actions = ttk.Frame(body)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.tutorial_back_button = ttk.Button(actions, text="Back", command=self.tutorial_back)
        self.tutorial_back_button.pack(side="left")
        self.tutorial_next_button = ttk.Button(actions, text="Next", command=self.tutorial_next)
        self.tutorial_next_button.pack(side="left", padx=8)
        self.tutorial_exit_button = ttk.Button(actions, text="Exit tutorial", command=self.tutorial_exit)
        self.tutorial_exit_button.pack(side="right")
        ttk.Label(actions, textvariable=self.tutorial_feedback, foreground="#176653", font=("Segoe UI", 8)).pack(side="left", padx=(5, 0))
        self.tutorial_bubble.bind("<Configure>", self._coach_resized, add="+")
        self._coach_canvas.bind("<Configure>", self._coach_resized, add="+")
        self._coach_copy.bind("<Configure>", self._coach_resized, add="+")
        for widget in (self._coach_canvas, self._coach_copy, *self._coach_keys, *self._coach_labels):
            widget.bind("<MouseWheel>", self._scroll_coach, add="+")
        self._coach_highlights = [tk.Frame(self.root, background="#0B9275") for _ in range(4)]

    def _coach_resized(self, event):
        self._fit_lesson_profile()
        width = max(1, self._coach_canvas.winfo_width())
        self._coach_canvas.itemconfigure(self._coach_copy_item, width=width)
        key_width = max(label.winfo_reqwidth() for label in self._coach_keys)
        for label in self._coach_labels:
            label.configure(wraplength=max(100, width - key_width - 16))
        maximum = max(100, min(210, int(self.root.winfo_height() * 0.30)))
        self._coach_canvas.configure(height=min(maximum, max(30, self._coach_copy.winfo_reqheight())), scrollregion=self._coach_canvas.bbox("all"))
        self._queue_tutorial_outline()

    def _fit_lesson_profile(self):
        if not self.tutorial_active or self.tutorial_id != "compress" or self._tutorial_snapshot is None:
            return
        font = self.lesson_profile_box.cget("font")
        unit = max(1, int(self.root.tk.call("font", "measure", font, "0")))
        available = self.page_scrollers["Create archive"].canvas.winfo_width() - 28
        width = min(int(self._tutorial_snapshot["profile_width"]), max(10, available // unit))
        if int(self.lesson_profile_box.cget("width")) != width:
            self.lesson_profile_box.configure(width=width)

    def _scroll_coach(self, event):
        if event.delta:
            self._coach_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _tutorial_window_changed(self, event):
        if event.widget is self.root:
            self._coach_resized(event)
            self._queue_tutorial_outline()

    def _queue_tutorial_outline(self):
        if self.tutorial_active and self._tutorial_outline_after is None:
            self._tutorial_outline_after = self.root.after_idle(self._refresh_tutorial_outline)

    def _refresh_tutorial_outline(self):
        self._tutorial_outline_after = None
        if self.tutorial_active:
            self._highlight_tutorial_target()

    def _scroll_page(self, event):
        super()._scroll_page(event)
        self._queue_tutorial_outline()

    def show_tutorials(self):
        if self.busy or self.tutorial_active:
            return
        if self._tutorial_catalog is not None and self._tutorial_catalog.winfo_exists():
            self._tutorial_catalog.lift()
            return
        dialog = tk.Toplevel(self.root)
        self._tutorial_catalog = dialog
        dialog.title("Rat-Trap — Show me how")
        dialog.transient(self.root)
        dialog.geometry("640x510")
        dialog.minsize(500, 400)
        page = desktop_app.ScrollPage(dialog)
        page.pack(fill="both", expand=True)
        frame = page.content
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="What would you like to learn?", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="Guided practice uses made-up files. Only the current step is clickable; Back and Exit remain available.", wraplength=530, style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 16))
        for index, spec in enumerate(tutorials.TUTORIALS):
            row = index * 3 + 2
            ttk.Label(frame, text=spec.title, font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(10, 0))
            ttk.Label(frame, text=spec.description, wraplength=530, style="Subtitle.TLabel").grid(row=row + 1, column=0, sticky="w", pady=4)
            if spec.available:
                ttk.Button(frame, text="Start guided practice", style="Action.TButton", command=lambda key=spec.id: self.start_tutorial(key)).grid(row=row + 2, column=0, sticky="w", pady=(0, 8))
            else:
                ttk.Label(frame, text="Feature available in the app · walkthrough coming later", style="Subtitle.TLabel").grid(row=row + 2, column=0, sticky="w")
        page.prepare()
        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(side="bottom", pady=10)

    def _copy_support_details(self):
        windows_app.RatTrapApp._copy_support_details(self)
        self.root.clipboard_append(f"\nInterface: Desktop Preview 2 with guided tutorials ({SUPPORT_VERSION})")

    def _capture_repository_tutorial_state(self):
        trees = {}
        for name in ("repository_snapshot_tree", "repository_history_tree"):
            tree = getattr(self, name)
            trees[name] = dict(rows=[(iid, tree.item(iid)) for iid in tree.get_children()],
                               selection=tree.selection(), focus=tree.focus(), xview=tree.xview(), yview=tree.yview(),
                               height=tree.cget("height"), displaycolumns=tree.cget("displaycolumns"), style=tree.cget("style"),
                               columns={column: tree.column(column) for column in tree.cget("columns")})
        return dict(trees=trees, loaded_path=self.repository_loaded_path,
                    snapshots=dict(self.repository_snapshots), history_ids=dict(self.repository_history_snapshot_ids),
                    mode=self.repository_result_tabs.select(), pin_text=self.repository_pin_button.cget("text"),
                    button_texts={name: getattr(self, name).cget("text") for name in ("history_source_button", "history_repository_button", "history_backup_button", "history_change_button", "history_refresh_button", "history_restore_button")})

    def _capture_tutorial_state(self):
        values = {name: getattr(self, name).get() for name in ("vault_archive", "vault_query", "vault_extension", "vault_result_count", "status_text", "activity_title", "activity_elapsed", "activity_hint", "activity_stage", "source_folder", "create_archive", "profile_label", "profile_note", "encrypt_created_archive", "extract_archive", "extract_folder", "seal_source", "seal_output", "unseal_source", "unseal_destination", "bulk_seal_source", "bulk_seal_output", "bulk_recovery_output", "protection_password_ack", "repository_path", "repository_source", "repository_label", "repository_search", "repository_status", "repository_keep_last", "repository_keep_daily", "repository_keep_weekly", "repository_keep_monthly", "history_restore_destination")}
        return dict(values=values, page=self.tabs.select(), archive=self.vault_results_archive,
                    rows=[(iid, self.vault_results.item(iid)) for iid in self.vault_results.get_children()],
                    selection=self.vault_results.selection(), focus=self.vault_results.focus(),
                    xview=self.vault_results.xview(), yview=self.vault_results.yview(),
                    preview=self.vault_preview.get("1.0", "end-1c"), preview_x=self.vault_preview.xview(), preview_y=self.vault_preview.yview(),
                    last_output=self.last_output, picker=self._picker_directory,
                    activity_outcome=self._activity_outcome, browse_text=self.vault_browse_button.cget("text"),
                    lesson_button_texts={name: getattr(self, name).cget("text") for name in ("lesson_source_button", "lesson_output_button", "lesson_create_button", "lesson_archive_button", "lesson_destination_button", "lesson_extract_button")},
                    profile_values=self.lesson_profile_box.cget("values"),
                    profile_width=self.lesson_profile_box.cget("width"),
                    secure_mode=self.secure_modes.select(),
                    repository_state=self._capture_repository_tutorial_state(),
                    protection_button_texts={name: getattr(self, name).cget("text") for name in ("protection_source_button", "protection_output_button", "protection_seal_button", "protection_restore_source_button", "protection_restore_destination_button", "protection_restore_button", "protection_recovery_button")},
                    page_views={name: (page.canvas.xview(), page.canvas.yview()) for name, page in self.page_scrollers.items()})

    def start_tutorial(self, tutorial_id="vault-search"):
        if self.busy or self.tutorial_active or tutorial_id not in tutorials.STEPS_BY_ID:
            return False
        if self._tutorial_catalog is not None and self._tutorial_catalog.winfo_exists():
            self._tutorial_catalog.destroy()
        self._tutorial_catalog = None
        self._tutorial_snapshot = self._capture_tutorial_state()
        self._tutorial_widget_states = {}
        self._tutorial_bindtags = {}
        for widget in _descendants(self.root):
            if self._inside(widget, self.tutorial_bubble) or widget in self._coach_highlights:
                continue
            self._tutorial_bindtags[widget] = widget.bindtags()
            widget.bindtags((self._coach_tag, *widget.bindtags()))
            if isinstance(widget, ttk.Widget) and not isinstance(widget, (ttk.Frame, ttk.Label, ttk.Separator)):
                self._tutorial_widget_states[widget] = ("ttk", widget.state(), widget.cget("takefocus"))
            elif isinstance(widget, (tk.Text, tk.Entry, tk.Listbox, tk.Button)):
                self._tutorial_widget_states[widget] = ("tk", widget.cget("state"), widget.cget("takefocus"))
        for sequence in ("<ButtonPress>", "<ButtonRelease>", "<KeyPress>", "<KeyRelease>", "<MouseWheel>"):
            self._tutorial_gate_commands.append(self.root.bind_class(self._coach_tag, sequence, self._tutorial_input_gate))
        self.tutorial_active = True
        self.tutorial_id = tutorial_id
        self.tutorial_session_token = object()
        self._tutorial_index = 0
        self._tutorial_error = ""
        self._tutorial_next_step = None
        self._tutorial_pending_action = None
        self._lesson_profile_used = None
        self._lesson_verification = None
        self._protection_key_selected = False
        self._protection_verification = None
        self._history_verification = None
        self.progress.master.pack_forget()
        self.tutorial_bubble.pack(fill="x", pady=(0, 10), before=self.tabs)
        if tutorial_id == "vault-search":
            self.vault_browse_button.configure(text="Load practice Vault")
        elif tutorial_id == "history":
            self._history_frame.grid()
            for name in ("repository_path", "repository_source", "repository_label", "repository_search", "history_restore_destination"):
                getattr(self, name).set("")
            self.repository_loaded_path = None
            self.repository_snapshots = {}
            self.repository_history_snapshot_ids = {}
            for tree in (self.repository_snapshot_tree, self.repository_history_tree):
                for iid in tree.get_children():
                    tree.delete(iid)
            self.repository_snapshot_tree.configure(displaycolumns=("label", "files"), height=3, style=self._history_tree_style)
            self.repository_snapshot_tree.column("label", width=390, minwidth=100, stretch=False)
            self.repository_snapshot_tree.column("files", width=55, minwidth=40, stretch=False)
            self._select_repository_mode(0)
            self.repository_status.set("Sample practice only")
            self.history_source_button.configure(text="Load sample folder")
            self.history_repository_button.configure(text="Use sample repository")
            self._write_history_result("No backup has run. This lesson uses fictional files in an unencrypted temporary repository.")
        elif tutorial_id == "protect":
            for frame in self._protection_frames:
                frame.grid()
            self.protection_password_ack.set(False)
            for variable in (self.seal_source, self.seal_output, self.unseal_source, self.unseal_destination):
                variable.set("")
            self.protection_source_button.configure(text="Load sample file")
            self.protection_output_button.configure(text="Use sample sealed location")
            self.protection_restore_source_button.configure(text="Use sample Sealed File")
            self.protection_restore_destination_button.configure(text="Use password restore folder")
            self._write_protection_result("No protection operation has run. Practice credentials are supplied internally; never enter a real password.")
            self._write_protection_result("No sample has been restored yet.", restoring=True)
            self._show_protection_step()
        else:
            self._lesson_frames[tutorial_id].grid()
            self._write_lesson_result("No practice operation has run yet.")
            if tutorial_id == "compress":
                self.source_folder.set("")
                self.create_archive.set("")
                self.encrypt_created_archive.set(False)
                labels = tuple(label for label, value in windows_app.PROFILE_OPTIONS.items() if value in ("balanced", "fast", "smallest"))
                self.lesson_profile_box.configure(values=labels)
                self.profile_label.set(labels[0])
                self.profile_note.set(windows_app.PROFILE_NOTES["balanced"])
                self.lesson_source_button.configure(text="Load sample folder")
                self.lesson_output_button.configure(text="Use safe archive location")
            else:
                self.extract_archive.set("")
                self.extract_folder.set("")
                self.lesson_archive_button.configure(text="Load sample archive")
                self.lesson_destination_button.configure(text="Use separate restore folder")
        self._fit_lesson_profile()
        self._refresh_tutorial(focus=True)
        return True

    @staticmethod
    def _inside(widget, ancestor):
        while widget is not None:
            if widget == ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _guard_workspace_select(self, page=None):
        if page is not None and self.tutorial_active and not self._tutorial_internal_navigation:
            return self._normal_workspace_select()
        return self._normal_workspace_select(page)

    def _go_to(self, title):
        if self.tutorial_active:
            if self.busy or self._tutorial_pending_action or self.tutorial_step != "navigate" or title != self._tutorial_workspace:
                return False
            self._tutorial_internal_navigation = True
            try:
                result = super()._go_to(title)
            finally:
                self._tutorial_internal_navigation = False
            if result:
                self._set_tutorial_step("load")
            return result
        return super()._go_to(title)

    def apply_launch_request(self, request):
        if not self.tutorial_active:
            super().apply_launch_request(request)

    def _open_existing(self, *, restore=False):
        if not self.tutorial_active:
            super()._open_existing(restore=restore)

    def _preselect_output_path(self, path, *, restore=False, vault=False):
        if not self.tutorial_active:
            super()._preselect_output_path(path, restore=restore, vault=vault)

    def _choose_data_archive(self):
        if not self.tutorial_active:
            super()._choose_data_archive()

    def _show_all_vault(self):
        if not self.tutorial_active:
            super()._show_all_vault()

    def _start_vault_extract_selected(self):
        if not self.tutorial_active:
            super()._start_vault_extract_selected()

    def _allowed_target(self):
        if self.tutorial_id == "history":
            return {"navigate": self.nav_buttons["Backups & history"], "load": self.history_source_button,
                    "repository": self.history_repository_button, "first": self.history_backup_button,
                    "change": self.history_change_button, "second": self.history_backup_button,
                    "history": self.history_refresh_button, "select": self.repository_snapshot_tree,
                    "destination": self.history_destination_button, "restore": self.history_restore_button,
                    "verify": self.history_verify_button, "finish": self.history_result}.get(self.tutorial_step)
        if self.tutorial_id == "protect":
            return {"navigate": self.nav_buttons["Secure files"], "load": self.protection_source_button,
                    "destination": self.protection_output_button, "password": self.protection_password_check,
                    "key": self.protection_key_button, "seal": self.protection_seal_button,
                    "open": self.protection_result, "restore-load": self.protection_restore_source_button,
                    "restore-destination": self.protection_restore_destination_button,
                    "password-restore": self.protection_restore_button, "recovery": self.protection_recovery_button,
                    "verify": self.protection_verify_button, "finish": self.protection_restore_result}.get(self.tutorial_step)
        if self.tutorial_id == "compress":
            return {"navigate": self.nav_buttons["Create archive"], "load": self.lesson_source_button,
                    "destination": self.lesson_output_button, "profile": self.lesson_profile_box,
                    "create": self.lesson_create_button, "finish": self.create_lesson_result}.get(self.tutorial_step)
        if self.tutorial_id == "restore":
            return {"navigate": self.nav_buttons["Extract archive"], "load": self.lesson_archive_button,
                    "destination": self.lesson_destination_button, "extract": self.lesson_extract_button,
                    "verify": self.lesson_verify_button, "finish": self.restore_lesson_result}.get(self.tutorial_step)
        return {"navigate": self.nav_buttons["Search Vault"], "load": self.vault_browse_button,
                "query": self.vault_search_entry, "search": self.vault_search_button,
                "select": self.vault_results, "preview": self.vault_preview_button,
                "finish": self.vault_preview}.get(self.tutorial_step)

    def _tutorial_input_gate(self, event):
        if not self.tutorial_active:
            return None
        if getattr(event, "keysym", "") == "Escape":
            self.tutorial_exit()
            return "break"
        # Scrolling a workspace is always harmless and keeps small windows usable.
        if isinstance(event.widget, ttk.Scrollbar) or str(event.type) == "38":
            return None
        if self.busy or self._tutorial_pending_action or event.widget != self.tutorial_target:
            return "break"
        return None

    def _tutorial_escape(self, _event=None):
        if self.tutorial_active:
            self.tutorial_exit()
            return "break"

    def _sample_selected(self):
        return (isinstance(self.tutorial_demo, tutorials.DemoVault) and self.tutorial_demo.is_intact()
                and Path(self.vault_archive.get().strip()).absolute() == self.tutorial_demo.archive)

    def _expected_row_selected(self):
        return self._sample_selected() and self._selected_vault_paths() == [tutorials.DEMO_PATH]

    def _can_tutorial_next(self):
        if self.busy or self._tutorial_pending_action:
            return False
        if self.tutorial_id == "history":
            return (self.tutorial_step == "select" and self._older_history_selected()
                    or self.tutorial_step == "finish" and self._history_verification is not None and self._history_verification.ok)
        if self.tutorial_id == "protect":
            return (self.tutorial_step == "password" and self._protection_creation_valid(require_key=False)
                    or self.tutorial_step == "open" and self._protection_sealed_valid()
                    or self.tutorial_step == "finish" and self._protection_verification is not None and self._protection_verification.ok)
        if self.tutorial_id == "compress":
            return (self.tutorial_step == "profile" and self._compression_selection_valid()
                    or self.tutorial_step == "finish" and self._practice_archive_valid())
        if self.tutorial_id == "restore":
            return self.tutorial_step == "finish" and self._lesson_verification is not None and self._lesson_verification.ok
        return ((self.tutorial_step == "query" and self._sample_selected() and self.vault_query.get().strip().casefold() == tutorials.DEMO_QUERY)
                or (self.tutorial_step == "select" and self._expected_row_selected())
                or self.tutorial_step == "finish")

    def _tutorial_input_changed(self, *_args):
        if self.tutorial_active:
            self.tutorial_next_button.configure(state="normal" if self._can_tutorial_next() else "disabled")

    def _refresh_tutorial(self, *, focus=False):
        if not self.tutorial_active or self._closing:
            return
        step = self._tutorial_steps[self._tutorial_index]
        self.tutorial_heading.set(f"GUIDED PRACTICE  {self._tutorial_index + 1}/{len(self._tutorial_steps)}  ·  {step.title}")
        self.tutorial_where.set(step.where)
        self.tutorial_action.set(step.action)
        self.tutorial_why.set(step.why)
        self.tutorial_expect.set(step.expect)
        self.tutorial_target = self._allowed_target()
        if self._tutorial_pending_action:
            self.tutorial_action.set("Your request is saved. Let the current practice operation finish safely.")
            self.tutorial_expect.set("Rat-Trap will then " + ("leave the tutorial and restore your previous screen." if self._tutorial_pending_action == "exit" else "go back one step. No file operation is undone."))
        elif self._tutorial_error:
            self.tutorial_expect.set(self._tutorial_error)
        self.tutorial_feedback.set("Please wait…" if self.busy else "Sample files only · Esc to exit")
        self.tutorial_back_button.configure(state="normal")
        self.tutorial_exit_button.configure(state="normal")
        self.tutorial_next_button.configure(text="Finish tutorial" if step.id == "finish" else "Next", state="normal" if self._can_tutorial_next() else "disabled")
        if self.tutorial_id == "history" and isinstance(self.tutorial_demo, history_tutorials.HistoryPractice):
            demo = self.tutorial_demo
            completed = (step.id == "first" and demo.first_snapshot is not None or step.id == "second" and demo.second_snapshot is not None)
            self.history_backup_button.configure(text="Review saved backup" if completed else "Back up now")
            self.history_change_button.configure(text="Review sample change" if demo.source_version == 2 else "Change the sample file")
            self.history_restore_button.configure(text="Review older restore" if demo.restore_result is not None else "Restore selected...")
            if not self._tutorial_pending_action:
                if completed:
                    self.tutorial_action.set("Click Review saved backup. This checks the completed snapshot without making another one.")
                elif step.id == "change" and demo.source_version == 2:
                    self.tutorial_action.set("Click Review sample change. The changed source is checked; it is not edited again.")
                elif step.id == "restore" and demo.restore_result is not None:
                    self.tutorial_action.set("Click Review older restore. It checks the existing recovered copy without overwriting it.")
        if self.tutorial_id == "compress":
            self.lesson_create_button.configure(text="Review created archive" if self._lesson_profile_used is not None else "Create")
            if step.id == "create" and self._lesson_profile_used is not None and not self._tutorial_pending_action:
                self.tutorial_action.set("Click Review created archive. To try a different setting, use Back to load a fresh sample folder.")
        elif self.tutorial_id == "restore":
            self.lesson_extract_button.configure(text="Review restored files" if self.tutorial_demo is not None and self.tutorial_demo.restore_metadata is not None else "Extract files")
            if step.id == "extract" and self.tutorial_demo is not None and self.tutorial_demo.restore_metadata is not None and not self._tutorial_pending_action:
                self.tutorial_action.set("Click Review restored files to check this run again. It will not overwrite the destination.")
        elif self.tutorial_id == "protect" and isinstance(self.tutorial_demo, protection_tutorials.ProtectionPractice):
            demo = self.tutorial_demo
            self.protection_seal_button.configure(text="Review protected sample" if demo.seal_result is not None else "Protect file")
            self.protection_restore_button.configure(text="Review password restore" if demo.password_result is not None else "Restore plaintext copy")
            self.protection_recovery_button.configure(text="Review key-only recovery" if demo.recovery_result is not None else "Recover sample without password")
            if not self._tutorial_pending_action:
                if step.id == "seal" and demo.seal_result is not None:
                    self.tutorial_action.set("Click Review protected sample. This checks the completed run without overwriting it.")
                elif step.id == "password-restore" and demo.password_result is not None:
                    self.tutorial_action.set("Click Review password restore. The existing sample copy will not be overwritten.")
                elif step.id == "recovery" and demo.recovery_result is not None:
                    self.tutorial_action.set("Click Review key-only recovery. The existing sample copy will not be overwritten.")
        for widget, (kind, state, takefocus) in self._tutorial_widget_states.items():
            allowed = (not self.busy and not self._tutorial_pending_action and widget == self.tutorial_target) or isinstance(widget, ttk.Scrollbar)
            if kind == "ttk":
                widget.state(["!disabled"] if allowed else ["disabled"])
            else:
                widget.configure(state=(state if allowed else "disabled"))
            widget.configure(takefocus=takefocus if allowed else 0)
        self._highlight_tutorial_target(focus=focus)
        if focus:
            if self._tutorial_focus_after is not None:
                self.root.after_cancel(self._tutorial_focus_after)
                self._tutorial_focus_after = None
            token, step_id = self.tutorial_session_token, self.tutorial_step
            def settled_focus():
                self._tutorial_focus_after = None
                if self.tutorial_active and token is self.tutorial_session_token and step_id == self.tutorial_step:
                    self._highlight_tutorial_target(focus=True)
            # Coach wrapping can change viewport height after the first scroll.
            # Correct once after layout settles, never on ordinary user scrolls.
            self._tutorial_focus_after = self.root.after_idle(settled_focus)

    def _highlight_tutorial_target(self, *, focus=False):
        for border in self._coach_highlights:
            border.place_forget()
        target = self.tutorial_target
        if target is None or self.busy or self._tutorial_pending_action:
            return
        self.root.update_idletasks()
        if focus:
            if target == self.nav_buttons[self._tutorial_workspace]:
                self._show_nav_button(target)
            else:
                page = self.page_scrollers[self._tutorial_workspace]
                y = target.winfo_rooty() - page.content.winfo_rooty()
                total = max(1, page.content.winfo_height())
                page.canvas.yview_moveto(max(0, y - 12) / total)
                x = target.winfo_rootx() - page.content.winfo_rootx()
                page.canvas.xview_moveto(max(0, x - 12) / max(1, page.content.winfo_width()))
            self.root.update_idletasks()
            target.focus_set()
        if not target.winfo_ismapped():
            return
        x = target.winfo_rootx() - self.root.winfo_rootx()
        y = target.winfo_rooty() - self.root.winfo_rooty()
        width, height = target.winfo_width(), target.winfo_height()
        # A scrolled-out target must not draw its outline over another control.
        clip = self.root if target == self.nav_buttons[self._tutorial_workspace] else self.page_scrollers[self._tutorial_workspace].canvas
        left = max(x, clip.winfo_rootx() - self.root.winfo_rootx())
        top = max(y, clip.winfo_rooty() - self.root.winfo_rooty())
        right = min(x + width, clip.winfo_rootx() - self.root.winfo_rootx() + clip.winfo_width())
        bottom = min(y + height, clip.winfo_rooty() - self.root.winfo_rooty() + clip.winfo_height())
        x, y, width, height = left, top, right - left, bottom - top
        if width <= 2 or height <= 2:
            return
        for border, bounds in zip(self._coach_highlights, ((x, y, width, 2), (x, y + height - 2, width, 2), (x, y, 2, height), (x + width - 2, y, 2, height))):
            border.place(x=bounds[0], y=bounds[1], width=bounds[2], height=bounds[3])
            border.lift()

    def _set_tutorial_step(self, step):
        self._tutorial_index = next(i for i, item in enumerate(self._tutorial_steps) if item.id == step)
        self._show_protection_step()
        if self.tutorial_id == "history":
            self._select_repository_mode(0)
            if step in ("first", "second"):
                self.repository_label.set(history_tutorials.FIRST_LABEL if step == "first" else history_tutorials.SECOND_LABEL)
        if self.tutorial_id == "protect" and isinstance(self.tutorial_demo, protection_tutorials.ProtectionPractice):
            if step == "recovery":
                self.unseal_destination.set(str(self.tutorial_demo.recovery_output))
            elif step == "password-restore":
                self.unseal_destination.set(str(self.tutorial_demo.password_output))
        self._tutorial_error = ""
        self._coach_canvas.yview_moveto(0)
        self._refresh_tutorial(focus=True)

    def tutorial_next(self):
        if not self.tutorial_active or not self._can_tutorial_next():
            return False
        if self.tutorial_step == "finish":
            self.tutorial_exit()
        elif self.tutorial_id == "history":
            self._set_tutorial_step("destination")
        elif self.tutorial_id == "protect":
            self._set_tutorial_step("key" if self.tutorial_step == "password" else "restore-load")
        else:
            self._set_tutorial_step("create" if self.tutorial_id == "compress" else "search" if self.tutorial_step == "query" else "preview")
        return True

    def tutorial_back(self):
        if not self.tutorial_active:
            return
        if self.busy:
            if self._tutorial_pending_action != "exit":
                self._tutorial_pending_action = "back"
                self.tutorial_session_token = object()
            self._refresh_tutorial()
            self._queue_tutorial_recovery()
            return
        if self._tutorial_index == 0:
            self.tutorial_exit()
            self.show_tutorials()
            return
        self._tutorial_next_step = None
        self._set_tutorial_step(self._tutorial_steps[self._tutorial_index - 1].id)

    def tutorial_exit(self):
        if not self.tutorial_active:
            return
        self.tutorial_session_token = object()  # Invalidate queued practice callbacks.
        self._tutorial_next_step = None
        if self.busy:
            self._tutorial_pending_action = "exit"
            self._refresh_tutorial()
            self._queue_tutorial_recovery()
            return
        self._end_tutorial()

    def _choose_vault_archive(self):
        if not self.tutorial_active:
            return super()._choose_vault_archive()
        if self.tutorial_id != "vault-search" or self.tutorial_step != "load" or self.busy or self._tutorial_pending_action:
            return
        def loaded(demo):
            if self.tutorial_demo is not None:
                self.tutorial_demo.cleanup()
            self.tutorial_demo = demo
            self.vault_archive.set(str(demo.archive))
            self.vault_query.set("")
            self.vault_extension.set("")
        self._tutorial_worker_kind = "load"
        try:
            self._run_task("Preparing tutorial sample...", tutorials.create_demo, loaded)
        finally:
            self._tutorial_worker_kind = None

    def _start_vault_search(self):
        if not self.tutorial_active:
            return super()._start_vault_search()
        if self.tutorial_id != "vault-search" or self.tutorial_step != "search" or self.busy or self._tutorial_pending_action:
            return
        if not self._sample_selected() or self.vault_query.get().strip().casefold() != tutorials.DEMO_QUERY or self.vault_extension.get().strip():
            self._tutorial_error = "The practice selection changed. Go Back and reload the practice Vault."
            self._refresh_tutorial()
            return
        self._tutorial_worker_kind = "search"
        try:
            super()._start_vault_search()
        finally:
            self._tutorial_worker_kind = None

    def _start_vault_preview(self):
        if not self.tutorial_active:
            return super()._start_vault_preview()
        if self.tutorial_id != "vault-search" or self.tutorial_step != "preview" or self.busy or self._tutorial_pending_action:
            return
        if not self._expected_row_selected():
            self._tutorial_error = "Choose the practice result first. Use Back to return to the result list."
            self._refresh_tutorial()
            return
        self._tutorial_worker_kind = "preview"
        try:
            super()._start_vault_preview()
        finally:
            self._tutorial_worker_kind = None

    def _normalize_path_variable(self, variable):
        if not self.tutorial_active:
            return super()._normalize_path_variable(variable)

    def _profile_changed(self, event=None):
        if self.tutorial_active:
            if not self._lesson_ready("compress", "profile"):
                return
            profile = windows_app.PROFILE_OPTIONS.get(self.profile_label.get())
            if profile not in ("fast", "balanced", "smallest"):
                return
            self.profile_note.set(windows_app.PROFILE_NOTES[profile])
            self._tutorial_input_changed()
            return
        return super()._profile_changed(event)

    def _lesson_ready(self, lesson, step):
        return self.tutorial_active and self.tutorial_id == lesson and self.tutorial_step == step and not self.busy and not self._tutorial_pending_action

    def _practice_archive_valid(self):
        return isinstance(self.tutorial_demo, archive_tutorials.ArchivePractice) and self.tutorial_demo.archive_is_intact()

    def _compression_selection_valid(self):
        demo = self.tutorial_demo
        return (isinstance(demo, archive_tutorials.ArchivePractice)
                and self.source_folder.get() == str(demo.source)
                and self.create_archive.get() == str(demo.archive)
                and not self.encrypt_created_archive.get()
                and windows_app.PROFILE_OPTIONS.get(self.profile_label.get()) in ("fast", "balanced", "smallest")
                and demo.source_is_intact())

    def _restore_selection_valid(self):
        demo = self.tutorial_demo
        return (isinstance(demo, archive_tutorials.ArchivePractice)
                and self.extract_archive.get() == str(demo.archive)
                and self.extract_folder.get() == str(demo.restored)
                and demo.archive_is_intact())

    def _lesson_problem(self, text):
        self._tutorial_error = text
        self._refresh_tutorial()

    def _run_lesson_task(self, kind, label, work, done):
        self._tutorial_worker_kind = kind
        try:
            self._run_task(label, work, done)
        finally:
            self._tutorial_worker_kind = None

    def _load_archive_practice(self):
        restoring = self.tutorial_id == "restore"
        def loaded(demo):
            if self.tutorial_demo is not None:
                self.tutorial_demo.cleanup()
            self.tutorial_demo = demo
            self._lesson_profile_used = None
            self._lesson_verification = None
            self._clear_completion()
            self._write_lesson_result("Sample archive ready; no files restored yet." if restoring else "Sample folder ready; no archive created yet.")
            if restoring:
                self.extract_archive.set(str(demo.archive))
                self.extract_folder.set("")
            else:
                self.source_folder.set(str(demo.source))
                self.create_archive.set("")
        self._run_lesson_task("archive-load", "Preparing tutorial sample...", lambda: archive_tutorials.create_practice(with_archive=restoring), loaded)

    def _choose_source(self):
        if not self.tutorial_active:
            return super()._choose_source()
        if self._lesson_ready("compress", "load"):
            self._load_archive_practice()

    def _choose_create_archive(self):
        if not self.tutorial_active:
            return super()._choose_create_archive()
        if not self._lesson_ready("compress", "destination"):
            return
        demo = self.tutorial_demo
        if not isinstance(demo, archive_tutorials.ArchivePractice) or not demo.source_is_intact() or self.source_folder.get() != str(demo.source):
            return self._lesson_problem("The sample source changed. Use Back to load a fresh sample folder.")
        self.create_archive.set(str(demo.archive))
        self._set_tutorial_step("profile")

    def _choose_extract_archive(self):
        if not self.tutorial_active:
            return super()._choose_extract_archive()
        if self._lesson_ready("restore", "load"):
            self._load_archive_practice()

    def _choose_extract_folder(self):
        if not self.tutorial_active:
            return super()._choose_extract_folder()
        if not self._lesson_ready("restore", "destination"):
            return
        if not self._practice_archive_valid() or self.extract_archive.get() != str(self.tutorial_demo.archive):
            return self._lesson_problem("The sample archive changed. Use Back to load a fresh sample archive.")
        self.extract_folder.set(str(self.tutorial_demo.restored))
        self._set_tutorial_step("extract")

    def _render_practice_archive(self, metadata):
        demo = self.tutorial_demo
        archive_bytes = demo.archive.stat().st_size
        original_bytes = metadata.total_bytes
        saved = (1 - archive_bytes / original_bytes) * 100 if original_bytes else 0.0
        size_change = f"Space saved: {saved:.1f}%" if saved >= 0 else f"Archive is {-saved:.1f}% larger (format overhead can outweigh savings)."
        self._write_lesson_result(f"Archive created — {metadata.file_count:,} sample files\nOriginal: {original_bytes:,} bytes\nArchive: {archive_bytes:,} bytes\n{size_change}\nSource files kept · Not encrypted\nSaved outside the source: {demo.archive}")

    def _start_create(self):
        if not self.tutorial_active:
            return super()._start_create()
        if not self._lesson_ready("compress", "create"):
            return
        if not self._compression_selection_valid():
            return self._lesson_problem("The practice selection changed. Use Back to load the sample again; personal paths and encryption are not used in this lesson.")
        demo = self.tutorial_demo
        profile = windows_app.PROFILE_OPTIONS[self.profile_label.get()]
        if self._lesson_profile_used is not None:
            if profile == self._lesson_profile_used and demo.archive_is_intact():
                self._render_practice_archive(demo.archive_metadata)
                self._set_tutorial_step("finish")
            else:
                self._lesson_problem("This run already has an archive. Use Back to load a fresh sample folder before trying another setting. Nothing was overwritten.")
            return
        def created(metadata):
            self._lesson_profile_used = profile
            self._render_practice_archive(metadata)
        self._run_lesson_task("archive-create", "Creating archive...", lambda: demo.create_archive(profile), created)

    def _start_extract(self):
        if not self.tutorial_active:
            return super()._start_extract()
        if not self._lesson_ready("restore", "extract"):
            return
        if not self._restore_selection_valid():
            return self._lesson_problem("The practice selection changed. Use Back to load the sample again; no personal archive or destination is used.")
        demo = self.tutorial_demo
        self._lesson_verification = None
        if demo.restore_metadata is not None:
            self._write_lesson_result("Reviewing this run — nothing overwritten.\nClick Check restored files to compare its current contents again.")
            self._set_tutorial_step("verify")
            return
        def restored(metadata):
            self._write_lesson_result(f"Restored {metadata.file_count:,} sample files into a separate folder.\n{demo.restored}\n\nComparison not run yet. Click Check restored files next.")
        self._run_lesson_task("archive-extract", "Extracting files...", demo.restore_archive, restored)

    def _verify_practice_restore(self):
        if not self._lesson_ready("restore", "verify"):
            return
        if not self._restore_selection_valid():
            return self._lesson_problem("The practice archive selection changed. Use Back to load a new sample archive.")
        demo = self.tutorial_demo
        self._lesson_verification = None
        def verified(report):
            self._lesson_verification = report
            if report.ok:
                self._write_lesson_result(f"Contents match — {report.matched_files:,}/{report.file_count:,} sample files\nCompared {report.total_bytes:,} restored bytes against the original sample SHA-256 hashes.\nNo missing, changed or unexpected files.\nOriginal sample files and archive kept until the lesson exits.")
            else:
                self._write_lesson_result(f"Comparison needs attention — {report.matched_files:,}/{report.file_count:,} files match.\nMissing: {len(report.missing_files)} · Changed: {len(report.changed_files)}\nUnexpected: {len(report.unexpected_files)} · Unsafe paths: {len(report.unsafe_paths)}\nNo success claimed. Exit or reload a fresh sample; nothing is overwritten.")
        self._run_lesson_task("archive-verify", "Checking restored practice files...", demo.verify_restored, verified)

    def _history_source_valid(self):
        demo = self.tutorial_demo
        return (isinstance(demo, history_tutorials.HistoryPractice)
                and self.repository_source.get() == str(demo.source) and demo.source_is_intact())

    def _history_repository_valid(self):
        demo = self.tutorial_demo
        return (isinstance(demo, history_tutorials.HistoryPractice)
                and self.repository_path.get() == str(demo.repository)
                and self.repository_loaded_path == demo.repository and demo.repository_is_intact())

    def _older_history_selected(self):
        demo = self.tutorial_demo
        if not self._history_repository_valid() or demo.first_snapshot is None or demo.second_snapshot is None:
            return False
        selected = self.repository_snapshot_tree.selection()
        first = demo.first_snapshot
        return (selected == (first.snapshot_id,)
                and self.repository_snapshots.get(first.snapshot_id) == first
                and first.snapshot_id in {snapshot.snapshot_id for snapshot in demo.history})

    def _choose_repository_source(self):
        if not self.tutorial_active:
            return super()._choose_repository_source()
        if not self._lesson_ready("history", "load"):
            return
        def loaded(demo):
            if not isinstance(demo, history_tutorials.HistoryPractice) or not demo.source_is_intact():
                raise RuntimeError("Invalid history practice result")
            if self.tutorial_demo is not None:
                self.tutorial_demo.cleanup()
            self.tutorial_demo = demo
            self._history_verification = None
            self.repository_source.set(str(demo.source))
            self.repository_path.set("")
            self.repository_label.set("")
            self.history_restore_destination.set("")
            self.repository_loaded_path = None
            self.repository_snapshots = {}
            self.repository_history_snapshot_ids = {}
            for tree in (self.repository_snapshot_tree, self.repository_history_tree):
                for iid in tree.get_children():
                    tree.delete(iid)
            self.repository_status.set("Original sample ready")
            self._clear_completion()
            self._write_history_result("Version one of the fictional source is ready.\nNo backup has been created. The source and practice repository will remain separate.")
        self._run_lesson_task("history-load", "Preparing fictional backup sample...", history_tutorials.create_practice, loaded)

    def _choose_repository(self):
        if not self.tutorial_active:
            return super()._choose_repository()
        if not self._lesson_ready("history", "repository"):
            return
        if not self._history_source_valid():
            return self._lesson_problem("The sample source changed. Use Back to load a fresh sample folder.")
        self.repository_path.set(str(self.tutorial_demo.repository))
        self._set_tutorial_step("first")

    def _render_history_backup(self, result):
        demo = self.tutorial_demo
        if not self._history_source_valid() or not demo.repository_is_intact():
            raise RuntimeError("Practice backup changed before its result could be displayed")
        self.repository_loaded_path = demo.repository
        number = 1 if result is demo.first_snapshot else 2
        count = int(demo.first_snapshot is not None) + int(demo.second_snapshot is not None)
        self.repository_status.set(f"{count} sample snapshot(s) saved")
        self._write_history_result(f"{result.label}\nSaved and verified {result.file_count:,} fictional files ({result.total_bytes:,} source bytes).\nChanged files: {result.changed_file_count:,} · Unchanged files: {result.unchanged_file_count:,}\nExisting data reused: {result.reused_bytes:,} bytes.\nThe source is kept. This practice repository is not encrypted.\n" + ("The first version remains saved." if number == 1 else "Both saved versions are kept; the current source still has the changed note."))

    def _start_repository_snapshot(self):
        if not self.tutorial_active:
            return super()._start_repository_snapshot()
        if not (self._lesson_ready("history", "first") or self._lesson_ready("history", "second")):
            return
        demo = self.tutorial_demo
        first = self.tutorial_step == "first"
        label = history_tutorials.FIRST_LABEL if first else history_tutorials.SECOND_LABEL
        if not self._history_source_valid() or self.repository_path.get() != str(demo.repository) or self.repository_label.get() != label:
            return self._lesson_problem("The sample backup selection changed. Use Back to check it; no personal repository will be used.")
        previous = demo.first_snapshot if first else demo.second_snapshot
        if previous is not None:
            if not self._history_repository_valid():
                return self._lesson_problem("The practice repository changed. Reload a fresh sample; existing files will not be replaced.")
            self._render_history_backup(previous)
            self._set_tutorial_step("change" if first else "history")
            return
        if not first and (demo.source_version != 2 or demo.first_snapshot is None or not self._history_repository_valid()):
            return self._lesson_problem("The changed sample and first backup must be intact before the second backup.")
        self._run_lesson_task("history-first" if first else "history-second", "Saving first sample backup..." if first else "Saving second sample backup...", demo.create_first_backup if first else demo.create_second_backup, self._render_history_backup)

    def _render_history_change(self, _result):
        if not self._history_source_valid() or self.tutorial_demo.source_version != 2:
            raise RuntimeError("Practice source change was not verified")
        next_action = "Back up again to save the changed sample as a second snapshot." if self.tutorial_demo.second_snapshot is None else "Both backups already exist. The next step reviews the second snapshot without adding another."
        self._write_history_result("The fictional Aurora note now contains version two.\nBefore: the meeting was on Monday.\nNow: the meeting is on Thursday.\nThe checklist was not changed.\nThe first backup still holds the original version. " + next_action)

    def _change_history_sample(self):
        if not self._lesson_ready("history", "change"):
            return
        demo = self.tutorial_demo
        if not self._history_source_valid() or not self._history_repository_valid() or demo.first_snapshot is None:
            return self._lesson_problem("The sample source or first backup changed. Reload a fresh sample or Exit.")
        if demo.source_version == 2:
            self._render_history_change(None)
            self._set_tutorial_step("second")
            return
        self._run_lesson_task("history-change", "Changing the fictional sample note...", demo.change_sample, self._render_history_change)

    def _render_history_list(self, snapshots):
        demo = self.tutorial_demo
        expected = {demo.first_snapshot.snapshot_id, demo.second_snapshot.snapshot_id}
        if (not self._history_repository_valid() or len(snapshots) != 2
                or {snapshot.snapshot_id for snapshot in snapshots} != expected):
            raise RuntimeError("Expected practice history was not verified")
        self.repository_snapshots = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
        for iid in self.repository_snapshot_tree.get_children():
            self.repository_snapshot_tree.delete(iid)
        for snapshot in snapshots:
            self.repository_snapshot_tree.insert("", "end", iid=snapshot.snapshot_id, values=(
                windows_app._format_time_ns(snapshot.created_at_ns), snapshot.label, demo.source.name,
                str(snapshot.file_count), windows_app._format_size(snapshot.total_bytes),
                f"{snapshot.changed_file_count} / -{snapshot.deleted_file_count}", "", snapshot.snapshot_id[:10]))
        self._select_repository_mode(0)
        self.repository_status.set("2 saved sample versions")
        self._write_history_result("Two real snapshots were read from the practice repository.\nChoose First backup — original sample in the table.\nThe older files will be restored into a separate folder, leaving the changed current source untouched.")

    def _start_repository_refresh(self):
        if not self.tutorial_active:
            return super()._start_repository_refresh()
        if not self._lesson_ready("history", "history"):
            return
        demo = self.tutorial_demo
        if not self._history_source_valid() or not self._history_repository_valid() or demo.second_snapshot is None:
            return self._lesson_problem("The sample repository or current source changed. Reload a fresh sample or Exit.")
        self._run_lesson_task("history-list", "Reading saved sample history...", demo.list_history, self._render_history_list)

    def _select_history_destination(self):
        if not self._lesson_ready("history", "destination"):
            return
        if not self._older_history_selected():
            return self._lesson_problem("Select the first sample backup before choosing its restore location.")
        self.history_restore_destination.set(str(self.tutorial_demo.restored))
        self._set_tutorial_step("restore")

    def _render_history_restore(self, result):
        demo = self.tutorial_demo
        if result is not demo.restore_result or not demo.restored_is_intact() or not self._history_source_valid():
            raise RuntimeError("Older practice restore changed before its result could be displayed")
        self._write_history_result(f"Older snapshot restored — {result.file_count:,} sample files.\nRecovered copy: {demo.restored}\nThe original saved version was restored; the current source still contains version two.\nClick Check the older files to independently compare both states.")

    def _start_repository_restore(self):
        if not self.tutorial_active:
            return super()._start_repository_restore()
        if not self._lesson_ready("history", "restore"):
            return
        demo = self.tutorial_demo
        if not self._older_history_selected() or not self._history_source_valid() or self.history_restore_destination.get() != str(demo.restored):
            return self._lesson_problem("The selected snapshot, source or destination changed. Use Back to check the sample choices.")
        if demo.restore_result is not None:
            if not demo.restored_is_intact():
                return self._lesson_problem("The older restored copy changed. Reload a fresh sample; nothing will be overwritten.")
            self._render_history_restore(demo.restore_result)
            self._set_tutorial_step("verify")
            return
        self._run_lesson_task("history-restore", "Restoring the older sample snapshot...", demo.restore_older, self._render_history_restore)

    def _verify_history_restore(self):
        if not self._lesson_ready("history", "verify"):
            return
        demo = self.tutorial_demo
        if not isinstance(demo, history_tutorials.HistoryPractice) or demo.restore_result is None:
            return self._lesson_problem("Restore the older sample before comparing the contents.")
        self._history_verification = None
        def verified(report):
            self._history_verification = report
            if report.ok:
                self._write_history_result(f"Contents match — {report.matched_files}/{report.file_count} old/current file checks.\nSHA-256 comparisons passed for both restored originals and both current source files.\nRecovered note: the meeting is on Monday.\nCurrent note: the meeting is now on Thursday.\nThe newer source was not rolled back. Both backups remain until the lesson exits.\nKeep independent backups. Finish removes only unchanged practice files; cleanup is not secure erasure.")
            else:
                self._write_history_result(f"Comparison needs attention — {report.matched_files}/{report.file_count} old/current checks match.\nMissing: {len(report.missing_files)} · Changed: {len(report.changed_files)}\nUnexpected: {len(report.unexpected_files)} · Unsafe paths: {len(report.unsafe_paths)}\nThe recovered files, current source or saved history did not pass. Reload a fresh sample or Exit; no success is claimed.")
        self._run_lesson_task("history-verify", "Comparing older and current sample contents...", demo.verify_restored, verified)

    def _protection_creation_valid(self, *, require_key=True):
        demo = self.tutorial_demo
        return (isinstance(demo, protection_tutorials.ProtectionPractice)
                and self.seal_source.get() == str(demo.source)
                and self.seal_output.get() == str(demo.sealed)
                and self.protection_password_ack.get() and demo.source_is_intact()
                and (not require_key or self._protection_key_selected))

    def _protection_sealed_valid(self):
        demo = self.tutorial_demo
        return (isinstance(demo, protection_tutorials.ProtectionPractice)
                and demo.sealed_is_intact() and demo.key_is_intact())

    def _protection_restore_valid(self, *, recovery=False):
        demo = self.tutorial_demo
        return (self._protection_sealed_valid()
                and self.unseal_source.get() == str(demo.sealed)
                and self.unseal_destination.get() == str(demo.recovery_output if recovery else demo.password_output))

    def _run_protection_task(self, kind, label, work, done):
        def private_work():
            try:
                return work()
            except Exception:
                # Even an unexpected engine error must not echo credentials.
                raise RuntimeError("The fictional protection practice could not complete. Reload the sample or exit.") from None
        self._run_lesson_task(kind, label, private_work, done)

    def _choose_seal_source(self):
        if not self.tutorial_active:
            return super()._choose_seal_source()
        if not self._lesson_ready("protect", "load"):
            return
        def loaded(demo):
            if not isinstance(demo, protection_tutorials.ProtectionPractice):
                raise RuntimeError("Invalid protection practice result")
            if self.tutorial_demo is not None:
                self.tutorial_demo.cleanup()
            self.tutorial_demo = demo
            self._protection_key_selected = False
            self._protection_verification = None
            self.protection_password_ack.set(False)
            self.seal_source.set(str(demo.source))
            for name in ("seal_output", "unseal_source", "unseal_destination"):
                getattr(self, name).set("")
            self._clear_completion()
            self._write_protection_result("Fictional sample file ready. Your own files are not used.\nNo protection or recovery operation has run yet.")
            self._write_protection_result("Two separate plaintext copies will be restored: one with the password and one with only the recovery key.", restoring=True)
        self._run_protection_task("protection-load", "Preparing fictional security sample...", protection_tutorials.create_practice, loaded)

    def _choose_seal_output(self):
        if not self.tutorial_active:
            return super()._choose_seal_output()
        if not self._lesson_ready("protect", "destination"):
            return
        demo = self.tutorial_demo
        if not isinstance(demo, protection_tutorials.ProtectionPractice) or not demo.source_is_intact() or self.seal_source.get() != str(demo.source):
            return self._lesson_problem("The sample source changed. Use Back to load a fresh sample file.")
        self.seal_output.set(str(demo.sealed))
        self._set_tutorial_step("password")

    def _select_practice_key(self):
        if not self._lesson_ready("protect", "key"):
            return
        if not self._protection_creation_valid(require_key=False):
            return self._lesson_problem("The sample selection or password acknowledgement changed. Use Back to check it.")
        self._protection_key_selected = True
        self._write_protection_result(f"Disposable practice password selected; it is not displayed or copied.\nSeparate practice recovery-key folder:\n{self.tutorial_demo.recovery_key.parent}\nThis temporary folder demonstrates separation; it is not a secure backup. A real recovery key must be kept safely away from the protected file.")
        self._set_tutorial_step("seal")

    def _render_practice_seal(self, _result):
        demo = self.tutorial_demo
        self._write_protection_result(f"Sample protected and verified.\nSealed File: {demo.sealed}\nRecovery-key folder: {demo.recovery_key.parent}\nOriginal fictional plaintext kept. A password OR its matching recovery key can unlock this file.\nThe password and key contents are not shown. Select Next to restore the sample.")

    def _start_seal_file(self):
        if not self.tutorial_active:
            return super()._start_seal_file()
        if not self._lesson_ready("protect", "seal"):
            return
        if not self._protection_creation_valid():
            return self._lesson_problem("The sample selection changed. Use Back to load a fresh sample; no personal file will be protected.")
        demo = self.tutorial_demo
        if demo.seal_result is not None:
            if not self._protection_sealed_valid():
                return self._lesson_problem("The protected sample or key changed. Reload a fresh sample; nothing will be overwritten.")
            self._render_practice_seal(demo.seal_result)
            self._set_tutorial_step("open")
            return
        self._run_protection_task("protection-seal", "Protecting and verifying sample file...", demo.seal, self._render_practice_seal)

    def _choose_unseal_source(self):
        if not self.tutorial_active:
            return super()._choose_unseal_source()
        if not self._lesson_ready("protect", "restore-load"):
            return
        if not self._protection_sealed_valid():
            return self._lesson_problem("The protected sample or key changed. Reload a fresh sample or Exit.")
        self.unseal_source.set(str(self.tutorial_demo.sealed))
        self.unseal_destination.set("")
        self._set_tutorial_step("restore-destination")

    def _choose_unseal_destination(self):
        if not self.tutorial_active:
            return super()._choose_unseal_destination()
        if not self._lesson_ready("protect", "restore-destination"):
            return
        if not self._protection_sealed_valid() or self.unseal_source.get() != str(self.tutorial_demo.sealed):
            return self._lesson_problem("The protected sample selection changed. Use Back to select the sample again.")
        self.unseal_destination.set(str(self.tutorial_demo.password_output))
        self._set_tutorial_step("password-restore")

    def _render_practice_password(self, _result):
        self._write_protection_result(f"Password restore completed.\nPlaintext sample copy: {self.tutorial_demo.password_output}\nThe generated practice password was used internally, without a recovery key.\nThe sealed file and original sample remain unchanged. Next, recover a second copy with only the recovery key.", restoring=True)

    def _start_unseal_file(self):
        if not self.tutorial_active:
            return super()._start_unseal_file()
        if not self._lesson_ready("protect", "password-restore"):
            return
        if not self._protection_restore_valid():
            return self._lesson_problem("The sample restore selection changed. Use Back to select the practice locations again.")
        demo = self.tutorial_demo
        if demo.password_result is not None:
            if not demo.password_output_is_intact():
                return self._lesson_problem("The password-restored copy changed. Reload a fresh sample; nothing will be overwritten.")
            self._render_practice_password(demo.password_result)
            self._set_tutorial_step("recovery")
            return
        self._run_protection_task("protection-password", "Restoring sample with practice password...", demo.restore_with_password, self._render_practice_password)

    def _render_practice_recovery(self, _result):
        self._write_protection_result(f"Recovery-key-only restore completed.\nSecond plaintext sample copy: {self.tutorial_demo.recovery_output}\nNo password was passed to this operation. The matching key alone unlocked the sample.\nNow check both recovered files against the original sample SHA-256 hash.", restoring=True)

    def _recover_practice_file(self):
        if not self._lesson_ready("protect", "recovery"):
            return
        demo = self.tutorial_demo
        if not self._protection_restore_valid(recovery=True) or demo.password_result is None:
            return self._lesson_problem("The sample recovery selection changed. Use Back to check the practice locations.")
        if demo.recovery_result is not None:
            if not demo.recovery_output_is_intact():
                return self._lesson_problem("The key-restored copy changed. Reload a fresh sample; nothing will be overwritten.")
            self._render_practice_recovery(demo.recovery_result)
            self._set_tutorial_step("verify")
            return
        self._run_protection_task("protection-recovery", "Recovering sample with key only...", demo.restore_with_recovery, self._render_practice_recovery)

    def _verify_practice_protection(self):
        if not self._lesson_ready("protect", "verify"):
            return
        demo = self.tutorial_demo
        if not isinstance(demo, protection_tutorials.ProtectionPractice) or demo.password_result is None or demo.recovery_result is None:
            return self._lesson_problem("Both practice recovery operations must complete before comparison.")
        self._protection_verification = None
        def verified(report):
            self._protection_verification = report
            if report.ok:
                self._write_protection_result(f"Contents match — {report.matched_files}/{report.file_count} recovered sample copies.\nBoth were compared against the original sample SHA-256 hash ({report.total_bytes:,} bytes checked).\nPassword restore and password-free recovery both passed.\nFor real files, keep your recovery key safe: losing both password and key means Rat-Trap cannot unlock them.\nFinish removes unchanged practice files; cleanup is not secure erasure.", restoring=True)
            else:
                self._write_protection_result(f"Comparison needs attention — {report.matched_files}/{report.file_count} copies match.\nMissing: {len(report.missing_files)} · Changed: {len(report.changed_files)}\nUnexpected: {len(report.unexpected_files)} · Unsafe paths: {len(report.unsafe_paths)}\nNo success claimed. Reload a fresh sample or Exit; nothing is overwritten.", restoring=True)
        self._run_protection_task("protection-verify", "Comparing both recovered sample files...", demo.verify_restored, verified)

    def _run_task(self, label, work, done):
        if not self.tutorial_active:
            return super()._run_task(label, work, done)
        kind = self._tutorial_worker_kind
        if kind not in {"load", "search", "preview", "archive-load", "archive-create", "archive-extract", "archive-verify", "protection-load", "protection-seal", "protection-password", "protection-recovery", "protection-verify", "history-load", "history-first", "history-change", "history-second", "history-list", "history-restore", "history-verify"} or self.busy or self._tutorial_pending_action:
            return
        token = self.tutorial_session_token
        self._tutorial_next_step = None
        self._tutorial_error = ""
        def completed(result):
            if not self.tutorial_active or token is not self.tutorial_session_token:
                if isinstance(result, (tutorials.DemoVault, archive_tutorials.ArchivePractice, protection_tutorials.ProtectionPractice, history_tutorials.HistoryPractice)):
                    result.cleanup()
                return
            done(result)
            if kind == "history-load" and isinstance(result, history_tutorials.HistoryPractice) and result.source_is_intact():
                self._tutorial_next_step = "repository"
            elif kind == "history-first" and result is self.tutorial_demo.first_snapshot and self._history_repository_valid():
                self._tutorial_next_step = "change"
            elif kind == "history-change" and self.tutorial_demo.source_version == 2 and self._history_source_valid():
                self._tutorial_next_step = "second"
            elif kind == "history-second" and result is self.tutorial_demo.second_snapshot and self._history_repository_valid():
                self._tutorial_next_step = "history"
            elif kind == "history-list" and result is self.tutorial_demo.history and len(result) == 2 and self._history_repository_valid():
                self._tutorial_next_step = "select"
            elif kind == "history-restore" and result is self.tutorial_demo.restore_result and self.tutorial_demo.restored_is_intact():
                self._tutorial_next_step = "verify"
            elif kind == "history-verify" and isinstance(result, archive_tutorials.RestoreVerification):
                if result.ok:
                    self._tutorial_next_step = "finish"
                else:
                    self._tutorial_error = "The comparison did not pass. Review the result; reload a fresh sample or Exit."
            elif kind == "protection-load" and isinstance(result, protection_tutorials.ProtectionPractice) and result.source_is_intact():
                self._tutorial_next_step = "destination"
            elif kind == "protection-seal" and self._protection_sealed_valid() and result is self.tutorial_demo.seal_result:
                self._tutorial_next_step = "open"
            elif kind == "protection-password" and result is self.tutorial_demo.password_result and self.tutorial_demo.password_output_is_intact():
                self._tutorial_next_step = "recovery"
            elif kind == "protection-recovery" and result is self.tutorial_demo.recovery_result and self.tutorial_demo.recovery_output_is_intact():
                self._tutorial_next_step = "verify"
            elif kind == "protection-verify" and isinstance(result, archive_tutorials.RestoreVerification):
                if result.ok:
                    self._tutorial_next_step = "finish"
                else:
                    self._tutorial_error = "The comparison did not pass. Review the result; reload a fresh sample or Exit."
            elif kind == "archive-load" and isinstance(result, archive_tutorials.ArchivePractice) and result.source_is_intact() and (self.tutorial_id == "compress" or result.archive_is_intact()):
                self._tutorial_next_step = "destination"
            elif kind == "archive-create" and self._practice_archive_valid() and result is self.tutorial_demo.archive_metadata:
                self._tutorial_next_step = "finish"
            elif kind == "archive-extract" and result is self.tutorial_demo.restore_metadata:
                self._tutorial_next_step = "verify"
            elif kind == "archive-verify" and isinstance(result, archive_tutorials.RestoreVerification):
                if result.ok:
                    self._tutorial_next_step = "finish"
                else:
                    self._tutorial_error = "The comparison did not pass. Review the result; reload a fresh sample or Exit."
            elif kind == "load" and isinstance(result, tutorials.DemoVault) and self._sample_selected():
                self._tutorial_next_step = "query"
            elif kind == "search" and self._sample_selected() and self.vault_results_archive == self.tutorial_demo.archive.resolve() and any(self.vault_results.item(iid, "values")[0] == tutorials.DEMO_PATH for iid in self.vault_results.get_children()):
                self._tutorial_next_step = "select"
            elif kind == "preview" and self._expected_row_selected() and tutorials.DEMO_MARKER in self.vault_preview.get("1.0", "end-1c"):
                self._tutorial_next_step = "finish"
            else:
                self._tutorial_error = "The expected practice result was not received. Try this step again, or use Back or Exit."
        super()._run_task(label, work, completed)
        if self.tutorial_active:
            self._refresh_tutorial()

    def _restore_task_controls(self):
        error = super()._restore_task_controls()
        if self.tutorial_active:
            self._refresh_tutorial()
        return error

    def _finish_task(self, result, done, error):
        try:
            super()._finish_task(result, done, error)
        finally:
            self._after_tutorial_task(error)

    def _fail_task_setup(self, event, exception, *, stage):
        try:
            super()._fail_task_setup(event, exception, stage=stage)
        finally:
            self._after_tutorial_task(exception)

    def _show_error_reference(self, *args, **kwargs):
        # The inherited lifecycle still records the failure. Do not interrupt a
        # requested exit with a modal from a now-abandoned practice operation.
        if self.tutorial_active and self._tutorial_pending_action == "exit":
            return
        return super()._show_error_reference(*args, **kwargs)

    def _recover_task_poll_failure(self, exception):
        if not self.tutorial_active:
            return super()._recover_task_poll_failure(exception)
        try:
            alive = self._worker_thread is not None and self._worker_thread.is_alive()
        except Exception:
            alive = True  # Unknown liveness must never unlock or delete inputs.
        if not alive:
            return super()._recover_task_poll_failure(exception)
        self._task_monitor_failed = True
        self._record_ui_exception("ui.worker.poll_failed", exception, stage="polling")
        self._tutorial_error = "The practice monitor was interrupted. The worker is protected; Back or Exit will wait for it to finish."
        self._refresh_tutorial()
        self._queue_tutorial_recovery()

    def _queue_tutorial_recovery(self):
        if self.tutorial_active and self.busy and self._task_monitor_failed and self._tutorial_recovery_after is None:
            try:
                token = self._task_token
                self._tutorial_recovery_after = self.root.after(200, lambda: self._retry_tutorial_monitor(token))
            except tk.TclError:
                self._tutorial_error = "The practice monitor is unavailable. Try Exit again after the operation finishes."

    def _retry_tutorial_monitor(self, token):
        self._tutorial_recovery_after = None
        if not self.tutorial_active or not self.busy or not self._task_monitor_failed or token is not self._task_token:
            return
        try:
            alive = self._worker_thread is not None and self._worker_thread.is_alive()
        except Exception:
            alive = True
        if alive:
            self._queue_tutorial_recovery()
            return
        # The stable queue can now be drained without racing a live worker.
        # Existing completion handling still validates results/session tokens.
        self._poll_task_events(token)

    def _after_tutorial_task(self, error=None):
        if not self.tutorial_active or self.busy:
            return
        if (self.tutorial_id == "history" and isinstance(self.tutorial_demo, history_tutorials.HistoryPractice)
                and self.tutorial_demo.first_snapshot is not None
                and self.repository_path.get() == str(self.tutorial_demo.repository)
                and self.tutorial_demo.repository_is_intact()):
            # A queued Back invalidates UI completion, not the safely saved backup.
            self.repository_loaded_path = self.tutorial_demo.repository
        if self.tutorial_id == "compress" and isinstance(self.tutorial_demo, archive_tutorials.ArchivePractice):
            # A Back request invalidates presentation callbacks, not a file
            # already safely published by the worker. Keep replay read-only.
            self._lesson_profile_used = self.tutorial_demo.profile
        pending = self._tutorial_pending_action
        self._tutorial_pending_action = None
        if pending == "exit":
            self._end_tutorial()
        elif pending == "back":
            self._tutorial_next_step = None
            self.tutorial_back()
        elif error is not None or self._activity_outcome == "review":
            self._tutorial_next_step = None
            self._tutorial_error = "That practice operation did not finish successfully. Retry the highlighted action, or use Back or Exit."
            self._refresh_tutorial()
        elif self._tutorial_next_step:
            step, self._tutorial_next_step = self._tutorial_next_step, None
            self._set_tutorial_step(step)
        else:
            self._refresh_tutorial()

    def _end_tutorial(self):
        if self.busy:
            return
        snapshot = self._tutorial_snapshot
        self.tutorial_active = False
        self.tutorial_session_token = None
        self._tutorial_pending_action = None
        self._tutorial_next_step = None
        self._stop_activity_clock(self._activity_token)
        self._activity_token = None
        if self._tutorial_focus_after is not None:
            self.root.after_cancel(self._tutorial_focus_after)
            self._tutorial_focus_after = None
        if self._tutorial_outline_after is not None:
            self.root.after_cancel(self._tutorial_outline_after)
            self._tutorial_outline_after = None
        if self._tutorial_recovery_after is not None:
            self.root.after_cancel(self._tutorial_recovery_after)
            self._tutorial_recovery_after = None
        self.tutorial_bubble.pack_forget()
        for border in self._coach_highlights:
            border.place_forget()
        self.tutorial_target = None
        for widget, tags in self._tutorial_bindtags.items():
            if widget.winfo_exists():
                widget.bindtags(tags)
        self._tutorial_bindtags.clear()
        for sequence in ("<ButtonPress>", "<ButtonRelease>", "<KeyPress>", "<KeyRelease>", "<MouseWheel>"):
            self.root.unbind_class(self._coach_tag, sequence)
        for command in self._tutorial_gate_commands:
            self.root.deletecommand(command)
        self._tutorial_gate_commands.clear()
        if snapshot is not None:
            # Unmap the practice workspace before restoring a different nested
            # table. Otherwise ttk stretches previously hidden columns to the
            # temporary practice width before we return to the previous page.
            self._normal_workspace_select(snapshot["page"])
            self.root.update_idletasks()
            self.vault_archive.set(snapshot["values"]["vault_archive"])
            self._clear_vault_state()
            for iid, item in snapshot["rows"]:
                self.vault_results.insert("", "end", iid=iid, **item)
            self.vault_results_archive = snapshot["archive"]
            self.vault_results.selection_set(snapshot["selection"])
            self.vault_results.focus(snapshot["focus"])
            self.vault_preview.configure(state="normal")
            self.vault_preview.delete("1.0", "end")
            self.vault_preview.insert("1.0", snapshot["preview"])
            self.vault_preview.configure(state="disabled")
            self._clear_completion()
            if snapshot["last_output"] is not None:
                self._publish_completion(snapshot["last_output"])
            for name, value in snapshot["values"].items():
                if name != "vault_archive":
                    getattr(self, name).set(value)
            self._picker_directory = snapshot["picker"]
            self._activity_outcome = snapshot["activity_outcome"]
            self.vault_browse_button.configure(text=snapshot["browse_text"])
            for name, text in snapshot["lesson_button_texts"].items():
                getattr(self, name).configure(text=text)
            for name, text in snapshot["protection_button_texts"].items():
                getattr(self, name).configure(text=text)
            self._select_protection_mode(snapshot["secure_mode"])
            repository_state = snapshot["repository_state"]
            self.repository_loaded_path = repository_state["loaded_path"]
            self.repository_snapshots = dict(repository_state["snapshots"])
            self.repository_history_snapshot_ids = dict(repository_state["history_ids"])
            for name, saved in repository_state["trees"].items():
                tree = getattr(self, name)
                # Restore column preferences as one group. Letting ttk stretch
                # between individual changes can inflate its cached request.
                for column in tree.cget("columns"):
                    tree.column(column, stretch=False)
                for iid in tree.get_children():
                    tree.delete(iid)
                for iid, item in saved["rows"]:
                    tree.insert("", "end", iid=iid, **item)
                tree.configure(height=saved["height"], displaycolumns=saved["displaycolumns"], style=saved["style"])
                for column, settings in saved["columns"].items():
                    tree.column(column, **{key: value for key, value in settings.items() if key not in ("id", "stretch")})
                # Recompute the requested width from the restored columns.
                tree.configure(displaycolumns=saved["displaycolumns"])
                tree.selection_set(saved["selection"])
                tree.focus(saved["focus"])
            self.repository_pin_button.configure(text=repository_state["pin_text"])
            for name, text in repository_state["button_texts"].items():
                getattr(self, name).configure(text=text)
            self._select_repository_mode(repository_state["mode"])
            self.lesson_profile_box.configure(values=snapshot["profile_values"])
            self.lesson_profile_box.configure(width=snapshot["profile_width"])
            self._normal_workspace_select(snapshot["page"])
        for widget, (kind, state, takefocus) in self._tutorial_widget_states.items():
            if not widget.winfo_exists():
                continue
            if kind == "ttk":
                widget.state(["!" + flag for flag in widget.state()])
                widget.state(state)
            else:
                widget.configure(state=state)
            widget.configure(takefocus=takefocus)
        self._tutorial_widget_states.clear()
        for frame in self._lesson_frames.values():
            frame.grid_remove()
        for frame in self._protection_frames:
            frame.grid_remove()
        self._history_frame.grid_remove()
        self.progress.master.pack(fill="x", side="bottom", pady=(12, 0), before=self.tabs)
        self.root.update_idletasks()
        if snapshot is not None:
            if self.tutorial_id == "history":
                # A longer practice action label can leave an unmapped table
                # at its former allocation even after its request shrinks.
                # Settle both restored tables before allowing columns to
                # stretch, so stale practice slack cannot widen user columns.
                self._normal_workspace_select(self.pages["Backups & history"])
                for mode in (0, 1):
                    self._select_repository_mode(mode)
                    self.root.update_idletasks()
                    self.page_scrollers["Backups & history"]._layout()
                    self.root.update_idletasks()
                self._select_repository_mode(snapshot["repository_state"]["mode"])
                self._normal_workspace_select(snapshot["page"])
                self.root.update_idletasks()
            else:
                self.page_scrollers["Backups & history"]._layout()
                self.root.update_idletasks()
            for name, saved in snapshot["repository_state"]["trees"].items():
                for column, settings in saved["columns"].items():
                    getattr(self, name).column(column, stretch=settings["stretch"])
            for name, (xview, yview) in snapshot["page_views"].items():
                self.page_scrollers[name].canvas.xview_moveto(xview[0])
                self.page_scrollers[name].canvas.yview_moveto(yview[0])
            self.vault_results.xview_moveto(snapshot["xview"][0])
            self.vault_results.yview_moveto(snapshot["yview"][0])
            self.vault_preview.xview_moveto(snapshot["preview_x"][0])
            self.vault_preview.yview_moveto(snapshot["preview_y"][0])
            for name, saved in snapshot["repository_state"]["trees"].items():
                getattr(self, name).xview_moveto(saved["xview"][0])
                getattr(self, name).yview_moveto(saved["yview"][0])
        self._tutorial_snapshot = None
        if self.tutorial_demo is not None:
            self.tutorial_demo.cleanup()
            self.tutorial_demo = None
        self._lesson_profile_used = None
        self._lesson_verification = None
        self._protection_key_selected = False
        self._protection_verification = None
        self._history_verification = None

    def _root_destroyed(self, event):
        if getattr(event, "widget", None) is self.root:
            if self._tutorial_focus_after is not None:
                self.root.after_cancel(self._tutorial_focus_after)
                self._tutorial_focus_after = None
            if self._tutorial_outline_after is not None:
                self.root.after_cancel(self._tutorial_outline_after)
                self._tutorial_outline_after = None
            if self._tutorial_recovery_after is not None:
                self.root.after_cancel(self._tutorial_recovery_after)
                self._tutorial_recovery_after = None
            self.tutorial_active = False
            self.tutorial_session_token = None
            # Normal close is guarded by the inherited worker lifecycle.
            if self.tutorial_demo is not None and not self.busy:
                self.tutorial_demo.cleanup()
                self.tutorial_demo = None
        super()._root_destroyed(event)


def _normal_only_action(name):
    """Guard original callbacks even when invoked without a widget click."""
    def guarded(self, *args, **kwargs):
        if not self.tutorial_active:
            return getattr(super(GuidedRatTrapApp, self), name)(*args, **kwargs)
    guarded.__name__ = name
    return guarded


# Every unrelated callback stays gated before it can inspect a selected path,
# show a picker/password dialog, or chain navigation and a second action.
_practice_callbacks = {"_choose_vault_archive", "_choose_source", "_choose_create_archive", "_choose_extract_archive", "_choose_extract_folder", "_start_create", "_start_extract", "_start_vault_search", "_start_vault_preview", "_choose_seal_source", "_choose_seal_output", "_choose_unseal_source", "_choose_unseal_destination", "_start_seal_file", "_start_unseal_file", "_choose_repository_source", "_choose_repository", "_start_repository_snapshot", "_start_repository_refresh", "_start_repository_restore"}
for _action_name in tuple(name for name in dir(desktop_preview2.DesktopPreview2App)
                          if name.startswith(("_choose_", "_start_", "_home_")) and name not in _practice_callbacks and name != "_start_activity_clock") + ("_open_result", "_show_result_folder"):
    setattr(GuidedRatTrapApp, _action_name, _normal_only_action(_action_name))


def _tutorial_self_test():
    with tempfile.TemporaryDirectory(prefix="rat-trap-guided-self-test-") as temporary:
        log = diagnostics.LocalDiagnostics(Path(temporary))
        root = tk.Tk()
        root.withdraw()
        try:
            app = GuidedRatTrapApp(root, diagnostic_log=log)
            def wait():
                deadline = time.monotonic() + 30
                while app.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                if app.busy:
                    raise RuntimeError("Tutorial worker timed out")
            if not app.start_tutorial() or not app._go_to("Search Vault"):
                raise RuntimeError("Tutorial did not start")
            app._choose_vault_archive()
            wait()
            if app.tutorial_step != "query":
                raise RuntimeError("Practice Vault was not prepared")
            app.vault_query.set(tutorials.DEMO_QUERY)
            app.tutorial_next()
            app._start_vault_search()
            wait()
            if app.tutorial_step != "select":
                raise RuntimeError("Practice search failed")
            iid = next(iid for iid in app.vault_results.get_children() if app.vault_results.item(iid, "values")[0] == tutorials.DEMO_PATH)
            app.vault_results.selection_set(iid)
            app.tutorial_next()
            app._start_vault_preview()
            wait()
            if app.tutorial_step != "finish" or tutorials.DEMO_MARKER not in app.vault_preview.get("1.0", "end-1c"):
                raise RuntimeError("Practice preview failed")
            sample = app.tutorial_demo.root
            app.tutorial_next()
            if app.tutorial_active or sample.exists() or app.tabs.select() != str(app.pages["Home"]):
                raise RuntimeError("Tutorial did not restore and clean up")
            for lesson in ("compress", "restore"):
                if not app.start_tutorial(lesson):
                    raise RuntimeError("Archive lesson did not start")
                app._go_to("Create archive" if lesson == "compress" else "Extract archive")
                if lesson == "compress":
                    app._choose_source()
                    wait()
                    app._choose_create_archive()
                    if not app.tutorial_next():
                        raise RuntimeError("Compression profile step failed")
                    app._start_create()
                    wait()
                    if app.tutorial_step != "finish" or not app.tutorial_demo.archive_is_intact():
                        raise RuntimeError("Practice compression failed")
                else:
                    app._choose_extract_archive()
                    wait()
                    app._choose_extract_folder()
                    app._start_extract()
                    wait()
                    if app.tutorial_step != "verify":
                        raise RuntimeError("Practice restore did not reach comparison")
                    app._verify_practice_restore()
                    wait()
                    if app.tutorial_step != "finish" or not app._lesson_verification.ok:
                        raise RuntimeError("Practice restored-file comparison failed")
                sample = app.tutorial_demo.root
                app.tutorial_next()
                if app.tutorial_active or sample.exists() or app.tabs.select() != str(app.pages["Home"]):
                    raise RuntimeError("Archive lesson did not restore and clean up")
            if not app.start_tutorial("protect") or not app._go_to("Secure files"):
                raise RuntimeError("Protection lesson did not start")
            app._choose_seal_source()
            wait()
            app._choose_seal_output()
            app.protection_password_check.invoke()
            if not app.tutorial_next():
                raise RuntimeError("Practice password acknowledgement failed")
            app._select_practice_key()
            app._start_seal_file()
            wait()
            if app.tutorial_step != "open" or not app.tutorial_next():
                raise RuntimeError("Practice protection failed")
            app._choose_unseal_source()
            app._choose_unseal_destination()
            app._start_unseal_file()
            wait()
            if app.tutorial_step != "recovery":
                raise RuntimeError("Practice password restore failed")
            app._recover_practice_file()
            wait()
            if app.tutorial_step != "verify":
                raise RuntimeError("Practice key-only recovery failed")
            app._verify_practice_protection()
            wait()
            if app.tutorial_step != "finish" or not app._protection_verification.ok:
                raise RuntimeError("Practice recovery comparison failed")
            sample = app.tutorial_demo.root
            app.tutorial_next()
            if app.tutorial_active or sample.exists() or app.tabs.select() != str(app.pages["Home"]):
                raise RuntimeError("Protection lesson did not restore and clean up")
            if not app.start_tutorial("history") or not app._go_to("Backups & history"):
                raise RuntimeError("History lesson did not start")
            app._choose_repository_source()
            wait()
            app._choose_repository()
            app._start_repository_snapshot()
            wait()
            if app.tutorial_step != "change":
                raise RuntimeError("First sample backup failed")
            app._change_history_sample()
            wait()
            app._start_repository_snapshot()
            wait()
            if app.tutorial_step != "history":
                raise RuntimeError("Second sample backup failed")
            app._start_repository_refresh()
            wait()
            if app.tutorial_step != "select":
                raise RuntimeError("Sample backup history was not listed")
            app.repository_snapshot_tree.selection_set(app.tutorial_demo.first_snapshot.snapshot_id)
            if not app.tutorial_next():
                raise RuntimeError("Older sample selection failed")
            app._select_history_destination()
            app._start_repository_restore()
            wait()
            if app.tutorial_step != "verify":
                raise RuntimeError("Older sample restore failed")
            app._verify_history_restore()
            wait()
            if app.tutorial_step != "finish" or not app._history_verification.ok:
                raise RuntimeError("Old and current sample comparison failed")
            sample = app.tutorial_demo.root
            app.tutorial_next()
            if app.tutorial_active or sample.exists() or app.tabs.select() != str(app.pages["Home"]):
                raise RuntimeError("History lesson did not restore and clean up")
        finally:
            root.destroy()
            log.close()


def main():
    if sys.argv[1:] in (["--ui-self-test"], ["--tutorial-self-test"]):
        _tutorial_self_test()
        return
    if "--self-test" in sys.argv or "--self-test-folder" in sys.argv:
        windows_app.main()
        return
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    log = diagnostics.LocalDiagnostics()
    root = None
    try:
        request = windows_app._parse_launch_request(sys.argv[1:])
        root = tk.Tk()
        app = GuidedRatTrapApp(root, diagnostic_log=log)
        if request is not None:
            app.apply_launch_request(request)
        root.mainloop()
    except Exception as exc:
        reference = log.record_exception("app.startup.failed", exc, details={"component": "windows_ui", "stage": "startup", "status": "failed"})
        if root is None:
            root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Rat-Trap", f"The desktop preview could not start.\n\nError reference: {reference}", parent=root)
        root.destroy()
    finally:
        log.close()


if __name__ == "__main__":
    main()
