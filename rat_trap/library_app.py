"""Additive, explicit-registration Library over the existing desktop workspaces."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import tkinter as tk
import types
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import desktop_app, desktop_preview2, diagnostics, guided_app, library, library_health, library_plans, library_restore, library_search, library_storage, windows_app

SUPPORT_VERSION = "5.7.0-desktop-preview.2-library.6"
PRIVACY_NOTICE = (
    "Local catalogue, not a backup: names, locations, saved plans, source paths and notes are stored "
    "unencrypted on this computer. Protected files stay locked. Do not put passwords or "
    "recovery keys in notes. Only items you explicitly add are tracked."
)
KINDS = {"archive": "Archive", "vault": "Searchable Vault", "protected_archive": "Locked archive",
         "sealed_file": "Sealed File", "repository": "Backup repository"}


def _display_date(value: str) -> str:
    if len(value) == 10:
        return value
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


class LibraryRatTrapApp(guided_app.GuidedRatTrapApp):
    def __init__(self, root, *, diagnostic_log=None, library_path=None):
        self.library_store = library.LibraryStore(library_path)
        self._library_updating = False
        self._library_items = {}
        self._library_events = {}
        self._library_projects = {}
        self._library_project_choices = {}
        self._library_search_results = {}
        self._library_search_cancel = None
        self._library_restore_hit = None
        self._library_restored_path = None
        self._library_health_results = {}
        self._library_health_items = {}
        self._library_health_cancel = None
        self._library_plans = {}
        self._library_plan_editing = None
        super().__init__(root, diagnostic_log=diagnostic_log)
        self._refresh_library_view()

    def _build_ui(self):
        super()._build_ui()
        self.root.title("Rat-Trap — Library & project timeline · Desktop Preview 2")

    def _build_home(self):
        super()._build_home()
        card = ttk.Frame(self.pages["Home"], padding=16, relief="solid", borderwidth=1)
        card.grid(row=6, column=0, sticky="ew", pady=(18, 0))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="YOUR PROJECTS, IN ONE PLACE", style="Eyebrow.TLabel").grid(sticky="w")
        ttk.Label(card, text="Keep track of what you stored, where it lives and what happened next.",
                  style="Subtitle.TLabel", wraplength=650).grid(sticky="w", pady=8)
        self._library_button(card, "Open your Library", lambda: self._go_to("Library")).grid(sticky="w")
        self._build_library()

    def _new_tab(self, title):
        if title != "Library":
            return super()._new_tab(title)
        page = desktop_app.ScrollPage(self.tabs)
        self.pages[title] = page.content
        self.page_scrollers[title] = page
        self.tabs.add_page(title, page)
        button = self._library_button(self._nav_container, "Library & timeline", lambda: self._go_to(title))
        button.configure(style="Nav.TButton")
        button.pack(fill="x", pady=2)
        self.nav_buttons[title] = button
        button.bind("<FocusIn>", lambda _event: self._show_nav_button(button), add="+")
        return page.content

    def _workspace_selected(self, title):
        if title != "Library":
            return super()._workspace_selected(title)
        self.workspace_title.set("Library & project timeline")
        for name, button in self.nav_buttons.items():
            button.configure(style="Selected.Nav.TButton" if name == title else "Nav.TButton")
        self._show_nav_button(self.nav_buttons[title])

    def _library_button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.action_buttons.append(button)
        return button

    def _build_library(self):
        page = self._new_tab("Library")
        page.columnconfigure(0, weight=1)
        ttk.Label(page, text="A HOME FOR WHAT YOU KEEP", style="Eyebrow.TLabel").grid(sticky="w")
        ttk.Label(page, text="Your Library", style="Title.TLabel").grid(sticky="w", pady=(8, 5))
        ttk.Label(page, text=PRIVACY_NOTICE, style="Subtitle.TLabel", wraplength=740).grid(sticky="ew", pady=(0, 12))
        self._library_button(page, "Store a folder…", self._library_store_open).grid(sticky="w", pady=(0, 10))
        self._library_button(page, "Backup plans", self._library_plans_open).grid(sticky="w", pady=(0, 10))
        actions = ttk.Frame(page)
        actions.grid(sticky="w", pady=(0, 12))
        for column, (text, command) in enumerate((
            ("Add archive / protected file…", self._library_add_file),
            ("Add backup repository…", self._library_add_repository),
            ("New project…", self._library_new_project),
        )):
            self._library_button(actions, text, command).grid(row=0, column=column, padx=(0, 8))
        filters = ttk.Frame(page)
        filters.grid(sticky="ew", pady=(0, 12))
        filters.columnconfigure(3, weight=1)
        self.library_project_filter = tk.StringVar(value="All projects")
        self.library_query = tk.StringVar()
        self.library_assignment = tk.StringVar(value="Unassigned")
        ttk.Label(filters, text="Project").grid(row=0, column=0, padx=(0, 8))
        self.library_project_box = ttk.Combobox(filters, textvariable=self.library_project_filter,
                                               state="readonly", width=23)
        self.library_project_box.grid(row=0, column=1, sticky="ew")
        ttk.Label(filters, text="Filter items").grid(row=0, column=2, padx=(14, 8))
        ttk.Entry(filters, textvariable=self.library_query, width=12).grid(row=0, column=3, sticky="ew")
        project_actions = ttk.Frame(page)
        project_actions.grid(sticky="w", pady=(0, 8))
        for text, command in (("Rename project…", self._library_rename_project),
                              ("Remove project…", self._library_delete_project),
                              ("Note for project", self._library_note_for_project)):
            self._library_button(project_actions, text, command).pack(side="left", padx=(0, 8))
        self.library_summary = tk.StringVar(value="Nothing added yet. Add an existing Rat-Trap file or repository above.")
        ttk.Label(page, textvariable=self.library_summary, style="Subtitle.TLabel", wraplength=740).grid(sticky="ew", pady=(0, 8))
        self.library_modes = ttk.Notebook(page)
        self.library_modes.grid(sticky="nsew")
        items = ttk.Frame(self.library_modes, padding=12)
        timeline = ttk.Frame(self.library_modes, padding=12)
        items.columnconfigure(0, weight=1)
        timeline.columnconfigure(0, weight=1)
        self.library_modes.add(items, text="Stored items")
        self.library_modes.add(timeline, text="Project timeline")
        self._build_library_store_form()
        self._build_library_search()
        self._build_library_restore()
        self._build_library_health()
        self._build_library_plans()
        self.library_tree = self._library_tree_widget(items, ("name", "type", "project", "status"),
                                                     ("Name", "Type", "Project", "Availability"), (220, 135, 150, 100))
        self.library_details = tk.StringVar(value="Select an item to see its location and last check.")
        ttk.Label(items, textvariable=self.library_details, wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=10)
        controls = ttk.Frame(items)
        controls.grid(sticky="w")
        for column, (text, command) in enumerate((
            ("Open workspace", self._library_open_selected), ("Refresh selected", self._library_refresh_selected),
            ("Locate moved item…", self._library_relink_selected), ("Remove from Library…", self._library_remove_selected),
        )):
            self._library_button(controls, text, command).grid(row=0, column=column, padx=(0, 8), pady=4)
        self._library_button(items, "Save another version…", self._library_store_selected_backup).grid(sticky="w", pady=6)
        assignment = ttk.Frame(items)
        assignment.grid(sticky="ew", pady=10)
        ttk.Label(assignment, text="Assign selected item to").pack(side="left", padx=(0, 8))
        self.library_assignment_box = ttk.Combobox(assignment, textvariable=self.library_assignment,
                                                  state="readonly", width=26)
        self.library_assignment_box.pack(side="left")
        self._library_button(assignment, "Assign", self._library_assign_project).pack(side="left", padx=8)
        self.library_timeline_tree = self._library_tree_widget(timeline, ("date", "event", "item"),
                                                              ("Date (local time)", "Event", "Stored item"), (150, 210, 230))
        self.library_event_details = tk.StringVar(value="Select an event. Snapshot dates come from the repository; notes use your chosen date.")
        ttk.Label(timeline, textvariable=self.library_event_details, wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=10)
        self._library_button(timeline, "Open selected event / version", self._library_open_event).grid(sticky="w")
        note_frame = ttk.Frame(page)
        note_frame.grid(sticky="ew", pady=(14, 0))
        note_frame.columnconfigure(0, weight=1)
        self.library_note_target = tk.StringVar(value="To add a note, select a stored item or filter to a project.")
        ttk.Label(note_frame, textvariable=self.library_note_target, wraplength=740).grid(row=0, column=0, columnspan=3, sticky="ew")
        self.library_note = tk.Text(note_frame, width=1, height=3, wrap="word", font=("Segoe UI", 10))
        self.library_note.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
        self.library_note_date = tk.StringVar(value=date.today().isoformat())
        ttk.Label(note_frame, text="Note date (YYYY-MM-DD)").grid(row=2, column=0, sticky="e", padx=8)
        ttk.Entry(note_frame, textvariable=self.library_note_date, width=13).grid(row=2, column=1)
        self._library_button(note_frame, "Add note", self._library_add_note).grid(row=2, column=2, padx=(8, 0))
        ttk.Label(page, text="Search entire Library finds filenames, projects and notes across all projects. Use Search Vault for indexed text. "
                  "Timeline shows up to 500 newest matching events. Source integrity is checked separately with Verify.",
                  style="Subtitle.TLabel", wraplength=740).grid(sticky="ew", pady=(14, 0))
        self.library_project_filter.trace_add("write", self._library_filter_changed)
        self.library_query.trace_add("write", self._library_filter_changed)
        self.library_tree.bind("<<TreeviewSelect>>", self._library_selection_changed)
        self.library_timeline_tree.bind("<<TreeviewSelect>>", self._library_event_selected)

    def _build_library_plans(self):
        form = ttk.Frame(self.library_modes, padding=12)
        form.columnconfigure(0, weight=1)
        self.library_plans_form = form
        self.library_modes.add(form, text="Backup plans")
        ttk.Label(form, text="SAVE THE SETUP. RUN IT WHEN YOU CHOOSE.", style="Eyebrow.TLabel").grid(sticky="w")
        ttk.Label(form, text="Manual versioned backups only. No schedules, background service or automatic deletion. "
                  "Plans remember plaintext folder locations; backup repositories are NOT encrypted.",
                  wraplength=680).grid(sticky="ew", pady=8)
        self.library_plans_tree = self._library_tree_widget(form, ("name", "project", "result", "success"),
            ("Plan", "Project", "Last attempt result", "Last successful backup"), (175, 130, 180, 165))
        self.library_plan_details = tk.StringVar(value="Select a saved plan. Saving settings does not create a backup.")
        ttk.Label(form, textvariable=self.library_plan_details, wraplength=680).grid(sticky="ew", pady=8)
        actions = ttk.Frame(form)
        actions.grid(sticky="w")
        for index, (text, callback) in enumerate((
                ("Back up now", self._library_plan_run), ("New plan", self._library_plan_new),
                ("Edit selected", self._library_plan_edit), ("Remove plan…", self._library_plan_delete),
                ("Review interrupted run…", self._library_plan_review), ("Library health", self._library_plan_health))):
            self._library_button(actions, text, callback).grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 8), pady=4)
        editor = ttk.LabelFrame(form, text="Plan settings — save before running", padding=10)
        editor.grid(sticky="ew", pady=12)
        editor.columnconfigure(1, weight=1)
        self.library_plan_name = tk.StringVar()
        self.library_plan_source = tk.StringVar()
        self.library_plan_destination = tk.StringVar()
        self.library_plan_project = tk.StringVar()
        self.library_plan_editor_status = tk.StringVar(value="New plan")
        for row, (label, variable) in enumerate((("Name", self.library_plan_name), ("Source folder", self.library_plan_source),
                                                ("Backup folder", self.library_plan_destination))):
            ttk.Label(editor, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8))
            ttk.Entry(editor, textvariable=variable, width=20).grid(row=row, column=1, sticky="ew", pady=4)
        self._library_button(editor, "Browse…", self._library_plan_source_choose).grid(row=1, column=2, padx=(8, 0))
        self._library_button(editor, "Browse…", self._library_plan_destination_choose).grid(row=2, column=2, padx=(8, 0))
        ttk.Label(editor, text="Project").grid(row=3, column=0, sticky="w")
        self.library_plan_project_box = ttk.Combobox(editor, textvariable=self.library_plan_project, state="readonly", width=25)
        self.library_plan_project_box.grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Label(editor, textvariable=self.library_plan_editor_status, wraplength=600).grid(row=4, column=0, columnspan=3, sticky="w", pady=5)
        self._library_button(editor, "Save plan", self._library_plan_save).grid(row=5, column=0, columnspan=3, sticky="w")
        self.library_plan_result = tk.StringVar(value="Nothing runs until you choose a saved plan and click Back up now.")
        ttk.Label(form, textvariable=self.library_plan_result, wraplength=680).grid(sticky="ew", pady=8)
        self.library_plans_tree.bind("<<TreeviewSelect>>", self._library_plan_selected)

    def _library_plans_refresh(self, selected_id=None):
        selected = self.library_plans_tree.selection()
        selected_id = selected_id or (selected[0] if selected else None)
        self._library_plans = {}
        self.library_plans_tree.delete(*self.library_plans_tree.get_children())
        choices = tuple(name for name, key in self._library_project_choices.items() if key)
        self.library_plan_project_box.configure(values=choices)
        try:
            plans = library_plans.list_plans(self.library_store)
        except (library.LibraryError, OSError) as exc:
            self.library_plan_result.set(f"Plans unavailable: {exc}")
            return
        self._library_plans = {plan.id: plan for plan in plans}
        for plan in plans:
            project = self._library_projects.get(plan.project_id)
            self.library_plans_tree.insert("", "end", iid=plan.id, values=(plan.name,
                project.name if project else "Project missing", plan.last_status,
                _display_date(plan.last_success_at) if plan.last_success_at else "Never"))
        if selected_id in self._library_plans:
            self.library_plans_tree.selection_set(selected_id)
        self.library_plan_details.set("Select a saved plan. Results are historical; health checks are separate.")

    def _library_plan_selected(self, *_args):
        if not self._library_guard():
            return
        plan = self._library_plan_selection()
        if plan:
            self.library_plan_details.set(library_plans.describe(plan))

    def _library_plan_selection(self):
        selected = self.library_plans_tree.selection()
        return self._library_plans.get(selected[0]) if selected else None

    def _library_plans_open(self):
        if self._library_guard():
            self._library_plans_refresh()
            self.library_modes.select(self.library_plans_form)

    def _library_plan_new(self):
        if not self._library_guard():
            return
        self._library_plan_editing = None
        self.library_plan_name.set("")
        self.library_plan_source.set("")
        self.library_plan_destination.set("")
        self.library_plan_project.set(next((name for name, key in self._library_project_choices.items()
                                           if key and key == self._library_project_id()), ""))
        self.library_plan_editor_status.set("New plan. Saving records settings only; no backup runs.")

    def _library_plan_edit(self):
        if not self._library_guard():
            return
        plan = self._library_plan_selection()
        if plan:
            self._library_plan_editing = plan
            self.library_plan_name.set(plan.name)
            self.library_plan_source.set(plan.source)
            self.library_plan_destination.set(plan.destination)
            self.library_plan_project.set(next((name for name, key in self._library_project_choices.items()
                                               if key == plan.project_id), ""))
            self.library_plan_editor_status.set("Editing saved plan. Changing source, destination or project resets its displayed run history; old timeline receipts remain.")

    def _library_plans_from_store(self):
        if not self._library_guard():
            return
        if self.store_mode.get() != "Versioned backup":
            messagebox.showinfo("Backup plans", "Choose Versioned backup first. Plans do not store passwords or create encrypted archives.", parent=self.root)
            return
        self._library_plan_new()
        self.library_plan_name.set(self.store_snapshot_label.get().strip() or Path(self.store_source.get()).name)
        self.library_plan_source.set(self.store_source.get())
        self.library_plan_destination.set(self.store_destination.get())
        self.library_modes.select(self.library_plans_form)

    def _library_plan_source_choose(self):
        if self._library_guard():
            selected = filedialog.askdirectory(parent=self.root, title="Choose the source folder for this plan", mustexist=True)
            if selected:
                self.library_plan_source.set(selected)

    def _library_plan_destination_choose(self):
        if self._library_guard():
            selected = filedialog.askdirectory(parent=self.root, title="Choose a new/empty backup folder or existing repository", mustexist=False)
            if selected:
                self.library_plan_destination.set(selected)

    def _library_plan_save(self):
        if not self._library_guard():
            return
        values = dict(name=self.library_plan_name.get(), source=self.library_plan_source.get(),
                      destination=self.library_plan_destination.get(),
                      project_id=self._library_project_choices.get(self.library_plan_project.get()),
                      previous=self._library_plan_editing)
        if not values["project_id"]:
            messagebox.showwarning("Save backup plan", "Choose an existing project for this plan.", parent=self.root)
            return
        if not messagebox.askyesno("Save backup plan?", "Save these settings as plaintext local Library metadata?\n\n"
                f"Name: {values['name']}\nSource: {values['source']}\nBackup: {values['destination']}\n"
                f"Project: {self.library_plan_project.get()}\n\n"
                "This accepts the currently selected source/destination identities. No backup runs now. "
                "Changing locations/project resets displayed run history; old receipts remain. No scheduling or encryption is enabled.", parent=self.root):
            return
        def work():
            try:
                return library_plans.save_plan(self.library_store, **values)
            except Exception as exc:
                return exc
        def done(result):
            if isinstance(result, Exception):
                self.library_plan_result.set(f"Plan not saved: {result}")
                messagebox.showwarning("Backup plan", str(result), parent=self.root)
                return
            self._library_plan_editing = result
            self._library_plans_refresh(result.id)
            self.library_plan_editor_status.set("Saved settings. Select the plan above and click Back up now when ready.")
            self.library_plan_result.set("Plan saved. No backup was started and no files were deleted.")
        self._run_task("Saving backup plan settings…", work, done)

    def _library_plan_run(self):
        if not self._library_guard():
            return
        plan = self._library_plan_selection()
        if not plan:
            messagebox.showinfo("Back up now", "Select a saved plan first.", parent=self.root)
            return
        project = self._library_projects.get(plan.project_id)
        if not messagebox.askyesno("Back up now?", f"Run saved plan: {plan.name}\n\nSource: {plan.source}\n"
                f"Backup: {plan.destination}\nProject: {project.name if project else 'Missing'}\n\n"
                "Uses SAVED settings, not unsaved edits below. Creates one version; keeps originals and older versions. "
                "NOT ENCRYPTED. Close editing apps first. Pending recovery work is refused, not resumed.", parent=self.root):
            return
        self.library_plan_result.set("Backing up… Please wait for the result. No background schedule is active.")
        def work():
            try:
                return library_plans.run_plan(self.library_store, plan, progress=self._queue_task_status)
            except Exception as exc:
                return exc
        def done(result):
            if isinstance(result, Exception):
                self.library_plan_result.set(f"Run not started: {result}")
                messagebox.showwarning("Backup plan", str(result), parent=self.root)
                return
            self._refresh_library_view()
            self._library_plans_refresh(result.plan.id)
            self.library_modes.select(self.library_plans_form)
            text = library_plans.describe(result.plan)
            if result.saved:
                text += f"\nSaved snapshot: {result.saved.snapshot_id}\nSaved at: {result.saved.path}"
            if result.record_error:
                text += "\n" + result.record_error + "\nDo not run again merely to repair the record. Review the repository first."
            self.library_plan_result.set(text)
            self.library_plan_details.set(text)
            if result.record_error or result.plan.last_status != "Succeeded":
                messagebox.showwarning("Backup plan result", text, parent=self.root)
            else:
                self.status_text.set("Backup saved — health verification is separate")
        self._run_task("Running saved backup plan…", work, done)

    def _library_plan_delete(self):
        if not self._library_guard():
            return
        plan = self._library_plan_selection()
        if plan and messagebox.askyesno("Remove backup plan?", f"Forget settings for {plan.name}?\n\n"
                "Source files, backup versions, Library entries and timeline receipts will stay.", parent=self.root):
            try:
                library_plans.delete_plan(self.library_store, plan)
                if self._library_plan_editing and self._library_plan_editing.id == plan.id:
                    self._library_plan_new()
                self._library_plans_refresh()
                self.library_plan_result.set("Plan settings removed. Stored work and timeline receipts were kept.")
            except (library.LibraryError, OSError) as exc:
                messagebox.showwarning("Backup plan", str(exc), parent=self.root)

    def _library_plan_review(self):
        if not self._library_guard():
            return
        plan = self._library_plan_selection()
        if plan and messagebox.askyesno("Acknowledge interrupted run?", "First inspect this repository in Backups & history:\n"
                f"{plan.destination}\n\nIt may contain a completed version or unfinished work. "
                "Have you reviewed it? Acknowledging only clears the plan's interrupted marker. "
                "It does not repair, recover, delete or mark a backup successful. Another active plan run will block this action.", parent=self.root):
            try:
                library_plans.acknowledge_interrupted(self.library_store, plan)
                self._library_plans_refresh(plan.id)
            except (library.LibraryError, OSError) as exc:
                messagebox.showwarning("Backup plan", str(exc), parent=self.root)

    def _library_plan_health(self):
        if self._library_guard():
            self.library_modes.select(self.library_health_form)

    def _build_library_health(self):
        form = ttk.Frame(self.library_modes, padding=12)
        form.columnconfigure(0, weight=1)
        self.library_health_form = form
        self.library_modes.add(form, text="Library health")
        ttk.Label(form, text="CHECK WHAT YOU KEEP", style="Eyebrow.TLabel").grid(sticky="w")
        ttk.Label(form, text="Explicit, read-only checks across ALL projects. Vault and backup contents are verified; "
                  "other archives are not verified here and protected contents stay locked. No repairs, recovery, "
                  "restores or deletion. Checks can take time; close other writers first.",
                  wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=8)
        row = ttk.Frame(form)
        row.grid(sticky="w")
        self._library_button(row, "Check Library…", self._library_health_start).pack(side="left", padx=(0, 8))
        self._library_button(row, "Check selected…", self._library_health_selected_start).pack(side="left", padx=(0, 8))
        self.library_health_cancel_button = ttk.Button(row, text="Cancel check", command=self._library_health_stop, state="disabled")
        self.library_health_cancel_button.pack(side="left")
        self.library_health_status = tk.StringVar(value="Historical results only. Nothing is scanned automatically; recheck after changes.")
        ttk.Label(form, textvariable=self.library_health_status, wraplength=700).grid(sticky="ew", pady=8)
        self.library_health_tree = self._library_tree_widget(form, ("name", "availability", "integrity", "date"),
            ("Stored item", "Availability", "Last integrity result", "Checked (local)"), (220, 100, 155, 145))
        self.library_health_details = tk.StringVar(value="Select an item for its check details. Available is not the same as verified.")
        ttk.Label(form, textvariable=self.library_health_details, wraplength=700).grid(sticky="ew", pady=8)
        actions = ttk.Frame(form)
        actions.grid(sticky="w")
        for text, callback in (("Locate moved item…", self._library_health_locate),
                               ("Open workspace", self._library_health_open),
                               ("Find a file to restore", self._library_health_restore)):
            self._library_button(actions, text, callback).pack(side="left", padx=(0, 8))
        ttk.Label(form, text="Results and dates are saved as unencrypted Library timeline notes, not file contents. "
                  "A previous Verified result is NOT a live guarantee or a second backup. Cancel may wait for the current "
                  "identity/database read; unfinished items are never marked Verified.",
                  wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=8)
        self.library_health_tree.bind("<<TreeviewSelect>>", self._library_health_selected)

    def _library_health_refresh(self, *, saved=True):
        self._library_health_items = {item.id: item for item in self.library_store.list_items()}
        if saved:
            self._library_health_results = library_health.latest_results(self.library_store, self._library_health_items.values())
        selected = self.library_health_tree.selection()
        self.library_health_tree.delete(*self.library_health_tree.get_children())
        for item in self._library_health_items.values():
            result = self._library_health_results.get(item.id)
            self.library_health_tree.insert("", "end", iid=item.id, values=(item.label,
                result.availability if result else "Not checked", result.status if result else "Not checked",
                _display_date(result.checked_at) if result else "—"))
        if selected and selected[0] in self._library_health_items:
            self.library_health_tree.selection_set(selected[0])

    def _library_health_selected(self, *_args):
        if not self._library_guard():
            return
        selection = self.library_health_tree.selection()
        item = self._library_health_items.get(selection[0]) if selection else None
        result = self._library_health_results.get(item.id) if item else None
        self.library_health_details.set((item.path + "\n" if item else "") +
            (library_health.describe(result) if result else "Not checked. Choose Check Library or Check selected; no integrity claim has been made."))

    def _library_health_selected_start(self):
        if self._library_guard():
            selection = self.library_health_tree.selection()
            if selection:
                self._library_health_start(item_ids=list(selection))

    def _library_health_start(self, *, item_ids=None):
        if not self._library_guard():
            return
        if not messagebox.askyesno("Check Library health?", "Read and verify stored data in " +
                ("the selected item" if item_ids else "ALL registered projects") +
                "?\n\nVaults and versioned backups are supported. Protected contents stay locked. "
                "No repair, restore, recovery or deletion. Results are saved as local unencrypted timeline receipts.", parent=self.root):
            return
        cancel = threading.Event()
        self._library_health_cancel = cancel
        self._library_health_results = {}
        self._library_health_refresh(saved=False)
        self.library_health_cancel_button.configure(state="normal")
        self.library_health_status.set("Checking stored data… Results below are from this run only.")
        def work():
            try:
                return library_health.check_library(self.library_store, item_ids=item_ids, cancel=cancel, progress=self._queue_task_status)
            except Exception as exc:
                return exc
        def done(report):
            self._library_health_cancel = None
            self.library_health_cancel_button.configure(state="disabled")
            if isinstance(report, Exception):
                self.library_health_status.set(f"Check did not complete; no previous results are shown. {report}")
                return
            self._library_health_results = {result.item_id: result for result in report.results}
            errors = sum(bool(result.receipt_error) for result in report.results)
            self.library_health_status.set(("Cancelled — incomplete check" if report.cancelled else "Check finished") +
                (" — item limit reached" if report.limited else "") +
                f". {len(report.results)} item(s) checked; {sum(r.status == 'Verified' for r in report.results)} verified; "
                f"{sum(r.status == 'Needs attention' for r in report.results)} need attention. " +
                (f"{errors} receipt(s) could not be saved. " if errors else "") + "Dated observations, not a live guarantee.")
            self._refresh_library_view()
            # Preserve this run's results, including receipt failures and cancellation.
            self._library_health_results = {result.item_id: result for result in report.results}
            self._library_health_refresh(saved=False)
        self._run_task("Checking Library health…", work, done)

    def _library_health_stop(self):
        if self._library_health_cancel is not None:
            self._library_health_cancel.set()
            self.library_health_status.set("Cancelling after the current read; unfinished items will not be verified.")
            self.library_health_cancel_button.configure(state="disabled")

    def _library_health_locate(self):
        if not self._library_guard():
            return
        selected = self.library_health_tree.selection()
        item = self._library_health_items.get(selected[0]) if selected else None
        if item:
            picker = filedialog.askdirectory if item.kind == "repository" else filedialog.askopenfilename
            path = picker(parent=self.root, title="Locate the SAME storage — identity will be checked")
            if path:
                self._library_task("Checking moved storage…", lambda: self.library_store.relink(item.id, path))

    def _library_health_open(self):
        if self._library_guard():
            selected = self.library_health_tree.selection()
            if selected:
                self._library_open_item(selected[0])

    def _library_health_restore(self):
        if self._library_guard():
            self.library_modes.select(self.library_search_form)
            self.library_search_details.set("Search for the file, choose its exact version, then Restore this file. Nothing restored automatically.")

    def _build_library_search(self):
        form = ttk.Frame(self.library_modes, padding=12)
        form.columnconfigure(0, weight=1)
        self.library_search_form = form
        self.library_modes.add(form, text="Search entire Library")
        ttk.Label(form, text="FIND WHAT YOU STORED", style="Eyebrow.TLabel").grid(sticky="w")
        ttk.Label(form, text="Search all projects, notes and filenames, regardless of the project filter above. "
                  "Locked items expose only their Library labels/notes, never their inner filenames. "
                  "Search runs only when you click Search; results stay in memory, with no permanent filename index.",
                  wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=8)
        row = ttk.Frame(form)
        row.grid(sticky="ew")
        row.columnconfigure(0, weight=1)
        self.library_search_query = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.library_search_query, width=20)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        entry.bind("<Return>", lambda _event: self._library_search_start())
        self._library_button(row, "Search", self._library_search_start).grid(row=0, column=1)
        # Intentionally outside action_buttons: cancellation must work while busy.
        self.library_search_cancel_button = ttk.Button(row, text="Cancel search", command=self._library_search_stop, state="disabled")
        self.library_search_cancel_button.grid(row=0, column=2, padx=8)
        self.library_search_filenames = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Include filenames inside unencrypted stored items (large solid archives can take time)",
                        variable=self.library_search_filenames).grid(sticky="w", pady=8)
        self.library_search_status = tk.StringVar(value="Enter part of a filename, project name or note. Nothing is extracted or opened automatically.")
        ttk.Label(form, textvariable=self.library_search_status, wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=8)
        self.library_search_tree = self._library_tree_widget(form, ("match", "kind", "project", "item", "version"),
            ("Match", "Type", "Project", "Stored in", "Backup version"), (220, 85, 120, 145, 160))
        self.library_search_details = tk.StringVar(value="Select a result to see its full location and exact version.")
        ttk.Label(form, textvariable=self.library_search_details, wraplength=700).grid(sticky="ew", pady=8)
        controls = ttk.Frame(form)
        controls.grid(sticky="w")
        self._library_button(controls, "Open result", self._library_search_open).pack(side="left", padx=(0, 8))
        self._library_button(controls, "Restore this file…", self._library_restore_prepare).pack(side="left", padx=(0, 8))
        self._library_button(controls, "Clear results", self._library_search_clear).pack(side="left")
        self.library_search_report = tk.Text(form, height=5, width=1, wrap="word", state="disabled", font=("Segoe UI", 9))
        self.library_search_report.grid(sticky="ew", pady=8)
        self.library_search_tree.bind("<<TreeviewSelect>>", self._library_search_selected)
        self.library_search_tree.bind("<Double-1>", lambda _event: self._library_search_open())

    def _build_library_restore(self):
        form = ttk.Frame(self.library_modes, padding=12)
        form.columnconfigure(0, weight=1)
        self.library_restore_form = form
        self.library_modes.add(form, text="Restore a file")
        ttk.Label(form, text="GET ONE FILE BACK", style="Eyebrow.TLabel").grid(sticky="w")
        self.library_restore_selection = tk.StringVar(value="Select a file in Search entire Library, then choose Restore this file.")
        ttk.Label(form, textvariable=self.library_restore_selection, wraplength=700).grid(sticky="ew", pady=10)
        ttk.Label(form, text="Restore only this file into a NEW folder, preserving its relative path. "
                  "Existing files/folders are never merged or overwritten. This stage supports unencrypted Vaults "
                  "and versioned backups, not ordinary or locked archives.",
                  wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=8)
        ttk.Label(form, text="New restore folder (its parent must already exist)").grid(sticky="w", pady=(8, 4))
        row = ttk.Frame(form)
        row.grid(sticky="ew")
        row.columnconfigure(0, weight=1)
        self.library_restore_destination = tk.StringVar()
        ttk.Entry(row, textvariable=self.library_restore_destination, width=20).grid(row=0, column=0, sticky="ew")
        self._library_button(row, "Choose parent folder…", self._library_restore_choose_destination).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(form, text="After success, a local unencrypted timeline receipt records the filename, "
                  "destination, checksum and exact backup version. No files will be opened or executed automatically.",
                  wraplength=700, style="Subtitle.TLabel").grid(sticky="ew", pady=12)
        controls = ttk.Frame(form)
        controls.grid(sticky="w")
        for label, callback in (("Restore file…", self._library_restore_start),
                                ("Show restored file", self._library_restore_show),
                                ("Back to search", self._library_restore_back)):
            self._library_button(controls, label, callback).pack(side="left", padx=(0, 8))
        self.library_restore_status = tk.StringVar(value="Nothing is restored until you confirm Restore file.")
        ttk.Label(form, textvariable=self.library_restore_status, wraplength=700).grid(sticky="ew", pady=12)

    def _library_restore_prepare(self):
        if not self._library_guard():
            return
        selected = self.library_search_tree.selection()
        hit = self._library_search_results.get(selected[0]) if selected else None
        try:
            if hit is None or hit.kind != "File" or not hit.member:
                raise library.LibraryError("Select an individual filename in Search entire Library first.")
            item = self.library_store.get_item(hit.item_id)
            if item.protected or item.kind not in {"vault", "repository"}:
                raise library.LibraryError("Direct restore currently supports unencrypted Vaults and versioned backups. Use Open result for this archive.")
        except library.LibraryError as exc:
            messagebox.showinfo("Restore from Library", str(exc), parent=self.root)
            return
        self._library_restore_hit = hit
        self._library_restored_path = None
        self.library_restore_destination.set("")
        self.library_restore_selection.set(f"File: {hit.member}\nProject: {hit.project}\nStored in: {item.path}\n"
            f"Version: {hit.snapshot_id or 'Vault archive'}" + (f" · {_display_date(hit.date)}" if hit.date else "") +
            f"\nSize: {windows_app._format_size(hit.size)}")
        self.library_restore_status.set("Choose a new restore folder. The source and exact version will be rechecked before publication.")
        self.library_modes.select(self.library_restore_form)

    def _library_restore_choose_destination(self):
        if not self._library_guard():
            return
        parent = filedialog.askdirectory(parent=self.root, title="Choose the parent for a NEW restore folder", mustexist=True)
        if parent:
            self.library_restore_destination.set(str(Path(parent) / ("Rat-Trap restored " + datetime.now().strftime("%Y-%m-%d %H%M%S"))))

    def _library_restore_back(self):
        if self._library_guard():
            self.library_modes.select(self.library_search_form)

    def _library_restore_show(self):
        if not self._library_guard():
            return
        if self._library_restored_path is None:
            messagebox.showinfo("Restore from Library", "No file has been restored by this form yet.", parent=self.root)
            return
        try:
            library._guard_path(self._library_restored_path)
            desktop_preview2.reveal_in_folder(self._library_restored_path)
        except (OSError, library.LibraryError) as exc:
            messagebox.showwarning("Restore from Library", f"The restored location is unavailable.\n\n{self._library_restored_path}\n\n{exc}", parent=self.root)

    def _library_restore_start(self):
        if not self._library_guard():
            return
        hit = self._library_restore_hit
        try:
            if hit is None or not self.library_restore_destination.get().strip():
                raise library.LibraryError("Select a search result and choose a new restore folder first.")
            destination = library_restore.validate_destination(self.library_store, self.library_restore_destination.get().strip())
        except (OSError, library.LibraryError) as exc:
            messagebox.showwarning("Restore from Library", str(exc), parent=self.root)
            return
        if not messagebox.askyesno("Restore exactly this file?",
                f"File: {hit.member}\nVersion: {hit.snapshot_id or 'Vault archive'}\n\n"
                f"New folder: {destination}\n\nOnly this file will be restored and verified. Existing files stay untouched. "
                "The filename, destination and version will be recorded in your local unencrypted timeline.", parent=self.root):
            return
        request = library_restore.RestoreRequest(hit, destination)
        self._library_restored_path = None
        self.library_restore_status.set("Restoring and verifying the selected file…")
        def work():
            try:
                return library_restore.restore_file(self.library_store, request, progress=self._queue_task_status)
            except Exception as exc:
                return exc
        def done(result):
            if isinstance(result, Exception):
                self.library_restore_status.set(f"Restore did not complete. No verified destination was published.\n{result}")
                messagebox.showwarning("Restore from Library", self.library_restore_status.get(), parent=self.root)
                return
            self._library_restored_path = result.path
            message = f"File restored and checksum verified.\n{result.path}\nSHA-256: {result.sha256}"
            if result.snapshot_id:
                message += f"\nExact snapshot: {result.snapshot_id}"
            if result.catalogue_error:
                message += "\n\nThe file is safe, but its timeline receipt could not be saved. Do not restore it again just to fix the timeline.\n" + result.catalogue_error
            else:
                message += "\nA File restored receipt was added to the project timeline."
            self.library_restore_status.set(message)
            try:
                self._refresh_library_view()
            except Exception:
                pass  # The verified output remains successful even if the view cannot refresh.
            (messagebox.showwarning if result.catalogue_error else messagebox.showinfo)("Restore from Library", message, parent=self.root)
        self._run_task("Restoring a file from Library…", work, done)

    def _library_search_clear(self):
        if not self._library_guard():
            return
        self._library_search_results.clear()
        self.library_search_tree.delete(*self.library_search_tree.get_children())
        self.library_search_details.set("Select a result to see its full location and exact version.")
        self.library_search_status.set("Results cleared. Enter a search and click Search.")
        self.library_search_report.configure(state="normal")
        self.library_search_report.delete("1.0", "end")
        self.library_search_report.configure(state="disabled")

    def _library_search_stop(self):
        if self._library_search_cancel is not None:
            self._library_search_cancel.set()
            self.library_search_status.set("Cancelling after the current identity/metadata check…")
            self.library_search_cancel_button.configure(state="disabled")

    def _library_search_start(self):
        if not self._library_guard():
            return
        query = self.library_search_query.get().strip()
        try:
            library._text(query, "Search", 300)
        except library.LibraryError as exc:
            messagebox.showinfo("Search Library", str(exc), parent=self.root)
            return
        filenames = self.library_search_filenames.get()
        self._library_search_clear()
        self.library_search_status.set(f"Searching all projects for: {query}")
        cancel = threading.Event()
        self._library_search_cancel = cancel
        self.library_search_cancel_button.configure(state="normal")
        def work():
            try:
                return library_search.search_library(self.library_store, query, filenames=filenames,
                    cancel=cancel, progress=self._queue_task_status)
            except Exception as exc:
                return exc
        def done(report):
            self._library_search_cancel = None
            self.library_search_cancel_button.configure(state="disabled")
            if isinstance(report, Exception):
                self.library_search_status.set("Search failed; no previous results are being shown.")
                messagebox.showwarning("Search Library", str(report), parent=self.root)
                return
            for index, hit in enumerate(report.results):
                key = str(index)
                self._library_search_results[key] = hit
                self.library_search_tree.insert("", "end", iid=key, values=(
                    hit.title.replace("\n", " ")[:220], hit.kind, hit.project, hit.item_label,
                    (_display_date(hit.date) + " · " + hit.snapshot_id[:10]) if hit.snapshot_id else "—"))
            state = "Cancelled — partial results" if report.cancelled else "Search finished"
            if report.limited or report.warnings:
                state += " — incomplete coverage"
            self.library_search_status.set(f"{state}: {len(report.results)} matches for ‘{query}’. "
                f"Filenames checked in {report.searched_items} item(s); {report.protected_items} locked item(s) skipped.")
            lines = ["Filename and catalogue search only, not full-text search or a storage integrity check."]
            if not filenames:
                lines.append("Filename search was turned off; these are catalogue-only results.")
            if report.limited:
                lines.append("Preview/result limit reached. Narrow your search; absence of a result is not proof it is missing.")
            if report.cancelled:
                lines.append("Cancelled. Only completed source checks are included; remaining items were not searched.")
            lines.extend(report.warnings)
            self.library_search_report.configure(state="normal")
            self.library_search_report.insert("1.0", "\n".join(lines))
            self.library_search_report.configure(state="disabled")
        self._run_task("Searching Library…", work, done)

    def _library_search_selected(self, *_args):
        if not self._library_guard():
            return
        selected = self.library_search_tree.selection()
        hit = self._library_search_results.get(selected[0]) if selected else None
        if hit:
            self.library_search_details.set(f"{hit.title}\nProject: {hit.project}\n{hit.path}\n" +
                (f"Exact snapshot: {hit.snapshot_id}\n" if hit.snapshot_id else "") + hit.detail)

    def _library_search_open(self):
        if not self._library_guard():
            return
        selected = self.library_search_tree.selection()
        hit = self._library_search_results.get(selected[0]) if selected else None
        if hit is None:
            return
        if hit.kind == "Note":
            messagebox.showinfo("Library note — as found by search", f"{hit.project} · {_display_date(hit.date)}\n\n{hit.detail}", parent=self.root)
        elif hit.kind == "Project":
            self._refresh_library_view()
            if hit.project_id not in self._library_projects:
                messagebox.showwarning("Search Library", "This project was removed. Search again.", parent=self.root)
                return
            project = self._library_projects[hit.project_id]
            self.library_query.set("")
            self.library_project_filter.set(f"{project.name} [{project.id[:8]}]")
            self.library_modes.select(0)
        elif hit.item_id:
            self._library_open_item(hit.item_id, hit.snapshot_id, search_result=hit)


    def _build_library_store_form(self):
        form = ttk.Frame(self.library_modes, padding=12)
        form.columnconfigure(1, weight=1)
        self.library_store_form = form
        self.library_modes.add(form, text="Store a folder")
        self.store_source = tk.StringVar()
        self.store_destination = tk.StringVar()
        self.store_mode = tk.StringVar(value="One-off archive")
        self.store_profile = tk.StringVar(value=next(iter(windows_app.PROFILE_OPTIONS)))
        self.store_encrypt = tk.BooleanVar(value=False)
        self.store_snapshot_label = tk.StringVar()
        self.store_notice = tk.StringVar()
        self.store_result = tk.StringVar(value="Choose a project above. Nothing is saved until you click Store folder.")
        ttk.Label(form, text="SAVE WORK TO THIS PROJECT", style="Eyebrow.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(form, text="Store as").grid(row=1, column=0, sticky="w", padx=(0, 10))
        ttk.Combobox(form, textvariable=self.store_mode, state="readonly",
                     values=("One-off archive", "Versioned backup"), width=24).grid(row=1, column=1, sticky="w", pady=5)
        for row, label, variable, command in (
                (2, "Source folder", self.store_source, self._library_store_choose_source),
                (3, "Save to", self.store_destination, self._library_store_choose_destination)):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10))
            ttk.Entry(form, textvariable=variable, width=20).grid(row=row, column=1, sticky="ew", pady=5)
            self._library_button(form, "Browse…", command).grid(row=row, column=2, padx=(8, 0))
        ttk.Label(form, text="Compression").grid(row=4, column=0, sticky="w", padx=(0, 10))
        self.store_profile_box = ttk.Combobox(form, textvariable=self.store_profile, state="readonly",
                                             values=tuple(windows_app.PROFILE_OPTIONS)[:3], width=34)
        self.store_profile_box.grid(row=4, column=1, sticky="w", pady=5)
        self.store_encryption_box = ttk.Checkbutton(form, text="Encrypt archive (password + separate recovery key)",
                                                    variable=self.store_encrypt, command=self._library_store_notice)
        self.store_encryption_box.grid(row=5, column=0, columnspan=3, sticky="w", pady=5)
        ttk.Label(form, text="Version label").grid(row=6, column=0, sticky="w", padx=(0, 10))
        self.store_label_entry = ttk.Entry(form, textvariable=self.store_snapshot_label, width=25)
        self.store_label_entry.grid(row=6, column=1, sticky="ew", pady=5)
        ttk.Label(form, textvariable=self.store_notice, style="Subtitle.TLabel", wraplength=620).grid(row=7, column=0, columnspan=3, sticky="ew", pady=10)
        buttons = ttk.Frame(form)
        buttons.grid(row=8, column=0, columnspan=3, sticky="w", pady=5)
        self._library_button(buttons, "Store folder", self._library_store_start).pack(side="left", padx=(0, 10))
        self._library_button(buttons, "Back to stored items", self._library_store_back).pack(side="left")
        self._library_button(form, "Save as backup plan…", self._library_plans_from_store).grid(row=10, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Label(form, textvariable=self.store_result, wraplength=620).grid(row=9, column=0, columnspan=3, sticky="ew", pady=10)
        self.store_mode.trace_add("write", self._library_store_mode_changed)
        self._library_store_notice()

    def _library_store_notice(self):
        backup = self.store_mode.get() == "Versioned backup"
        self.store_profile_box.configure(state="disabled" if backup else "readonly")
        self.store_encryption_box.configure(state="disabled" if backup else "normal")
        self.store_label_entry.configure(state="normal" if backup else "disabled")
        if backup:
            self.store_encrypt.set(False)
            text = ("NOT ENCRYPTED. Choose a new/empty backup folder or an existing Rat-Trap repository. "
                    "Each completed save adds a version; earlier versions stay. Uses the repository's compression settings.")
        else:
            text = ("ENCRYPTED ARCHIVE. You will choose a password and a new recovery-key file. Temporary plaintext requires your acknowledgement."
                    if self.store_encrypt.get() else "NOT ENCRYPTED. Tick Encrypt archive if you need password protection.")
            text += " Choose a new .gmw filename; existing archives are never replaced."
        self.store_notice.set(text + " Original files stay untouched. Keep an independent backup.")

    def _library_store_mode_changed(self, *_args):
        # A file destination must never accidentally become a repository path.
        self.store_destination.set("")
        self._library_store_notice()

    def _library_store_open(self):
        if not self._library_guard():
            return
        if not self._library_project_id():
            messagebox.showinfo("Store a folder", "Create or choose a project in the Project filter first.", parent=self.root)
            return
        self.library_modes.select(self.library_store_form)

    def _library_store_back(self):
        if self._library_guard():
            self.library_modes.select(0)

    def _library_store_choose_source(self):
        if self._library_guard():
            selected = filedialog.askdirectory(parent=self.root, title="Choose the folder to store — originals will be kept", mustexist=True)
            if selected:
                self.store_source.set(selected)

    def _library_store_choose_destination(self):
        if not self._library_guard():
            return
        if self.store_mode.get() == "Versioned backup":
            selected = filedialog.askdirectory(parent=self.root, title="Choose a new/empty backup folder or an existing repository", mustexist=False)
        else:
            selected = filedialog.asksaveasfilename(parent=self.root, title="Save a new archive outside the source folder",
                                                   defaultextension=".gmw", filetypes=[("Rat-Trap archive", "*.gmw")])
        if selected:
            self.store_destination.set(selected)

    def _library_store_selected_backup(self):
        if not self._library_guard():
            return
        item = self._library_selected_item()
        if not item:
            return
        if item.kind != "repository" or not item.project_id:
            messagebox.showinfo("Save another version", "Select a backup repository assigned to a project. Archives use a new filename for each save.", parent=self.root)
            return
        self.library_project_filter.set(next(name for name, key in self._library_project_choices.items() if key == item.project_id))
        self.store_mode.set("Versioned backup")
        self.store_source.set("")  # Do not guess a source in a multi-source repository.
        self.store_destination.set(item.path)
        self.store_snapshot_label.set("")
        self.store_result.set("Choose the source folder for this new version. Earlier versions will be kept.")
        self.library_modes.select(self.library_store_form)

    def _library_store_start(self):
        if not self._library_guard():
            return
        if not self.store_source.get().strip() or not self.store_destination.get().strip():
            messagebox.showwarning("Store a folder", "Choose both the source folder and where to save it.", parent=self.root)
            return
        request = library_storage.StoreRequest(
            Path(self.store_source.get().strip()), Path(self.store_destination.get().strip()),
            self._library_project_id(), "backup" if self.store_mode.get() == "Versioned backup" else "archive",
            windows_app.PROFILE_OPTIONS.get(self.store_profile.get(), "invalid"), self.store_snapshot_label.get())
        # Full path/identity checks run on the worker. Passwords are only ever
        # requested by the existing foreground consent flow, never stored.
        if not request.project_id:
            messagebox.showwarning("Store a folder", "Choose a project in the Project filter first.", parent=self.root)
            return
        encryption = {}
        if self.store_encrypt.get() and request.mode == "archive":
            encryption = self._new_encryption_options(request.destination, action="Creating this Library archive")
            if encryption is None:
                return
        recovery_path = encryption.get("recovery_key_output")
        self.store_result.set("Saving… Original files will be kept. Please wait for the result.")

        def work():
            try:
                return library_storage.store_folder(self.library_store, request, encryption=encryption,
                                                     progress=self._queue_task_status)
            except Exception as exc:
                return exc
            finally:
                encryption.clear()

        def done(result):
            if isinstance(result, BaseException):
                text = (f"Save did not complete: {result}\nNo Library success was recorded. Original files were not deleted. "
                        "If backup work was interrupted, use Backups & history to inspect or resume it. "
                        "An encryption attempt may leave a recovery-key file; keep it until you have checked the output.")
                self.store_result.set(text)
                self.status_text.set("Store folder did not complete")
                messagebox.showwarning("Store a folder", text, parent=self.root)
                return
            if result.catalogue_error:
                text = (f"Files saved, but Library could not be updated.\n{result.path}\n"
                        + (f"Exact snapshot: {result.snapshot_id}\n" if result.snapshot_id else "")
                        + "Do not save again just to fix the listing. Use Add archive / protected file or Add backup repository, "
                        "then Refresh selected for an existing item.\n" + result.catalogue_error)
                self.store_result.set(text)
                self.status_text.set("Saved — Library update needs attention")
                messagebox.showwarning("Saved; Library needs attention", text, parent=self.root)
                return
            self._refresh_library_view()
            choice = next((name for name, key in self._library_project_choices.items() if key == request.project_id), "All projects")
            self.library_project_filter.set(choice)
            self.library_query.set("")
            self._refresh_library_view(result.item.id)
            self.library_modes.select(0)
            protection = "Encrypted archive" if result.encrypted else "Not encrypted"
            text = (f"Saved to your Library. {result.file_count:,} files · {windows_app._format_size(result.total_bytes)} original data.\n"
                    f"{protection}\n{result.path}\nOriginals kept. Use Open workspace to check or restore your stored files.")
            if recovery_path:
                text += f"\nRecovery key: {recovery_path}\nKeep this key separately and safely."
            if result.resumed:
                text += ("\nResumed an interrupted backup. It may represent the earlier job's source state. "
                         "Check its version, then save again if you need changes made since that job began.")
            self.store_result.set(text)
            self.status_text.set("Folder saved and added to Library")
            messagebox.showinfo("Folder stored", text, parent=self.root)
        self._run_task("Storing folder in Library…", work, done)

    @staticmethod
    def _library_tree_widget(parent, columns, headings, widths):
        frame = ttk.Frame(parent)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=7)
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, minwidth=60, stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return tree

    def _library_guard(self):
        return not self.busy and not self.tutorial_active and not getattr(self, "_closing", False)

    def _library_project_id(self):
        return self._library_project_choices.get(self.library_project_filter.get())

    def _library_selected_item(self, warn=True):
        selected = self.library_tree.selection()
        item = self._library_items.get(selected[0]) if selected else None
        if item is None and warn:
            messagebox.showinfo("Rat-Trap Library", "Select a stored item first.", parent=self.root)
        return item

    def _library_filter_changed(self, *_args):
        if not self._library_updating and self._library_guard():
            self._refresh_library_view()

    def _refresh_library_view(self, selected_id=None):
        if self._library_updating or not self._library_guard():
            return
        self._library_updating = True
        try:
            old_selection = self.library_tree.selection()
            selected_id = selected_id or (old_selection[0] if old_selection else None)
            projects = self.library_store.list_projects()
            self._library_projects = {p.id: p for p in projects}
            self._library_project_choices = {f"{p.name} [{p.id[:8]}]": p.id for p in projects}
            values = list(self._library_project_choices)
            self.library_project_box.configure(values=["All projects", "Unassigned", *values])
            self.library_assignment_box.configure(values=["Unassigned", *values])
            if self.library_project_filter.get() not in ("All projects", "Unassigned", *values):
                self.library_project_filter.set("All projects")
            items = self.library_store.list_items(project_id=self._library_project_id(), query=self.library_query.get())
            if self.library_project_filter.get() == "Unassigned":
                items = [item for item in items if item.project_id is None]
            self._library_items = {item.id: item for item in items}
            self.library_tree.delete(*self.library_tree.get_children())
            for item in items:
                project = self._library_projects.get(item.project_id)
                self.library_tree.insert("", "end", iid=item.id, values=(item.label, KINDS.get(item.kind, "Unsupported"),
                                          project.name if project else "Unassigned", item.status))
            if selected_id in self._library_items:
                self.library_tree.selection_set(selected_id)
            filtered = bool(self.library_query.get().strip()) or self.library_project_filter.get() == "Unassigned"
            events = self.library_store.timeline(project_id=self._library_project_id(), limit=500,
                                                  item_ids=list(self._library_items) if filtered else None)
            self._library_events = {event.id: event for event in events}
            self.library_timeline_tree.delete(*self.library_timeline_tree.get_children())
            for event in events:
                item = self._library_items.get(event.item_id)
                self.library_timeline_tree.insert("", "end", iid=event.id, values=(
                    _display_date(event.occurred_at), event.title, item.label if item else "Project note"))
            self.library_summary.set(f"{len(items):,} stored item(s) · {len(events):,} timeline event(s) shown · "
                                     "Cached catalogue — Refresh selected checks a source again.")
            self.library_event_details.set("Select an event to see its date source and details.")
            self._library_health_refresh()
            self._library_plans_refresh()
        except (library.LibraryError, OSError) as exc:
            self.library_summary.set(f"Library unavailable: {exc}")
        finally:
            self._library_updating = False
        self._library_selection_changed()

    def _library_selection_changed(self, *_args):
        if self._library_updating or not self._library_guard():
            return
        item = self._library_selected_item(warn=False)
        if item:
            size = "not calculated" if item.kind == "repository" else windows_app._format_size(item.size_bytes)
            self.library_details.set(f"{item.path}\n{KINDS.get(item.kind, 'Unsupported')} · size {size} · {item.status} at "
                                     f"{_display_date(item.last_checked_at)}\nLibrary ID: {item.id}")
            selected_project = next((name for name, key in self._library_project_choices.items() if key == item.project_id), "Unassigned")
            self.library_assignment.set(selected_project)
            self.library_note_target.set(f"Note for stored item: {item.label}")
        else:
            self.library_details.set("Select an item to see its location. Removing it here never deletes the stored files.")
            project = self._library_projects.get(self._library_project_id())
            self.library_note_target.set(f"Note for project: {project.name}" if project else "To add a note, select a stored item or filter to a project.")

    def _library_event_selected(self, *_args):
        if not self._library_guard():
            return
        selected = self.library_timeline_tree.selection()
        event = self._library_events.get(selected[0]) if selected else None
        if event:
            self.library_event_details.set(f"{event.title} · {_display_date(event.occurred_at)} ({event.date_source})\n"
                                           f"{event.detail}" + (f"\nSnapshot: {event.snapshot_id}" if event.snapshot_id else ""))

    def _library_task(self, label, work, done=None):
        if not self._library_guard():
            return
        def safely():
            try:
                return work()
            except (library.LibraryError, OSError) as exc:
                return exc
        def completed(value):
            if isinstance(value, BaseException):
                self._refresh_library_view()
                messagebox.showwarning("Rat-Trap Library", str(value), parent=self.root)
                return
            self._refresh_library_view(getattr(value, "id", None))
            if done:
                done(value)
        self._run_task(label, safely, completed)

    def _library_add_file(self):
        if not self._library_guard():
            return
        selected = filedialog.askopenfilename(parent=self.root, title="Add an existing Rat-Trap file to Library",
                                              filetypes=[("Rat-Trap files", "*.gmw *.db *.rtsf")])
        if selected:
            project_id = self._library_project_id()
            self._library_task("Adding file to Library…", lambda: self.library_store.register(selected, project_id=project_id),
                               lambda item: self._library_registered(item, project_id))

    def _library_add_repository(self):
        if not self._library_guard():
            return
        selected = filedialog.askdirectory(parent=self.root, title="Add an existing backup repository", mustexist=True)
        if selected:
            project_id = self._library_project_id()
            self._library_task("Reading repository history for Library…", lambda: self.library_store.register(selected, project_id=project_id),
                               lambda item: self._library_registered(item, project_id))

    def _library_registered(self, item, requested_project):
        self.library_query.set("")
        if item.project_id != requested_project:
            actual = next((name for name, key in self._library_project_choices.items() if key == item.project_id), "Unassigned")
            self.library_project_filter.set(actual)
            self._refresh_library_view(item.id)
            messagebox.showinfo("Already in Library", "This item was already registered. Its existing project assignment "
                                "has been kept. Use Assign to change it.", parent=self.root)
        else:
            self._refresh_library_view(item.id)

    def _library_new_project(self):
        if not self._library_guard():
            return
        name = simpledialog.askstring("New project", "Project name (stored locally, unencrypted):", parent=self.root)
        if name is not None:
            def done(project):
                self.library_project_filter.set(f"{project.name} [{project.id[:8]}]")
            self._library_task("Creating Library project…", lambda: self.library_store.create_project(name), done)

    def _library_assign_project(self):
        if not self._library_guard():
            return
        item = self._library_selected_item()
        choice = self.library_assignment.get()
        if item and choice in ("Unassigned", *self._library_project_choices):
            project_id = self._library_project_choices.get(choice)
            self._library_task("Assigning Library project…", lambda: self.library_store.assign_project(item.id, project_id))

    def _library_rename_project(self):
        if not self._library_guard():
            return
        project = self._library_projects.get(self._library_project_id())
        if not project:
            messagebox.showinfo("Rat-Trap Library", "Choose a project in the Project filter first.", parent=self.root)
            return
        name = simpledialog.askstring("Rename project", "New project name:", initialvalue=project.name, parent=self.root)
        if name is not None:
            def done(updated):
                self.library_project_filter.set(f"{updated.name} [{updated.id[:8]}]")
            self._library_task("Renaming Library project…", lambda: self.library_store.rename_project(project.id, name, project.description), done)

    def _library_delete_project(self):
        if not self._library_guard():
            return
        project = self._library_projects.get(self._library_project_id())
        if not project:
            messagebox.showinfo("Rat-Trap Library", "Choose a project in the Project filter first.", parent=self.root)
            return
        if messagebox.askyesno("Remove project", f"Remove the project {project.name}?\n\nStored items stay in the Library, "
                              "unassigned. Notes remain in the overall timeline. No stored files are deleted.", parent=self.root):
            self._library_task("Removing Library project…", lambda: self.library_store.delete_project(project.id))

    def _library_note_for_project(self):
        if not self._library_guard():
            return
        if not self._library_project_id():
            messagebox.showinfo("Rat-Trap Library", "Choose a project in the Project filter first.", parent=self.root)
            return
        self.library_tree.selection_remove(*self.library_tree.selection())
        self._library_selection_changed()
        self.library_note.focus_set()

    def _library_add_note(self):
        if not self._library_guard():
            return
        item = self._library_selected_item(warn=False)
        project_id = None if item else self._library_project_id()
        text = self.library_note.get("1.0", "end-1c")
        note_date = self.library_note_date.get().strip()
        def done(_event):
            if self.library_note.get("1.0", "end-1c") == text:
                self.library_note.delete("1.0", "end")
            self.library_modes.select(1)
        self._library_task("Saving Library note…", lambda: self.library_store.add_note(
            text, item_id=item.id if item else None, project_id=project_id, event_date=note_date), done)

    def _library_refresh_selected(self):
        if not self._library_guard():
            return
        item = self._library_selected_item()
        if item:
            self._library_task("Checking Library source…", lambda: self.library_store.refresh(item.id))

    def _library_relink_selected(self):
        if not self._library_guard():
            return
        item = self._library_selected_item()
        if not item:
            return
        picker = filedialog.askdirectory if item.kind == "repository" else filedialog.askopenfilename
        selected = picker(parent=self.root, title="Locate the same stored item — identity will be checked")
        if selected:
            self._library_task("Checking moved item identity…", lambda: self.library_store.relink(item.id, selected))

    def _library_remove_selected(self):
        if not self._library_guard():
            return
        item = self._library_selected_item()
        if item and messagebox.askyesno("Remove from Library", f"Remove {item.label} and its Library notes/history?\n\n"
                                        "The actual archive or repository will NOT be deleted.", parent=self.root):
            self._library_task("Removing Library entry…", lambda: self.library_store.remove_item(item.id))

    def _library_open_selected(self):
        if self._library_guard():
            item = self._library_selected_item()
            if item:
                self._library_open_item(item.id)

    def _library_open_event(self):
        if not self._library_guard():
            return
        selected = self.library_timeline_tree.selection()
        event = self._library_events.get(selected[0]) if selected else None
        if event and event.kind == "note" and event.title == "File restored":
            messagebox.showinfo("Restore receipt", event.detail, parent=self.root)
            return
        if event and event.kind == "note" and event.title == "Library health check":
            item = self.library_store.get_item(event.item_id)
            result = library_health.parse_receipt(event.detail, item)
            messagebox.showinfo("Health check receipt", library_health.describe(result) if result else
                "This receipt is invalid or refers to a previous item location/project. Run a fresh health check.", parent=self.root)
            return
        if event and event.item_id:
            self._library_open_item(event.item_id, snapshot_id=event.snapshot_id)
        else:
            messagebox.showinfo("Rat-Trap Library", "Select an event linked to stored files. Project-only notes have no file to open.", parent=self.root)

    def _library_open_item(self, item_id, snapshot_id=None, *, search_result=None):
        if not self._library_guard():
            return
        def work():
            if search_result is not None:
                return library_search.validate_result(self.library_store, search_result)
            item = self.library_store.refresh(item_id)
            if item.status != "available":
                raise library.LibraryError(f"This item is {item.status}. Check its location or use Locate moved item. No files were opened.")
            inspection = self.library_store.inspect_item(item.id)
            if inspection.identity != item.identity or inspection.kind != item.kind:
                raise library.LibraryError("The source changed while being opened. Refresh and check it again.")
            if snapshot_id and snapshot_id not in {s.snapshot_id for s in inspection.repository_snapshots}:
                raise library.LibraryError("That exact snapshot is no longer available. No other version has been selected.")
            return item, inspection
        def done(result):
            item, inspection = result
            if item.kind == "repository":
                self._library_render_repository(Path(item.path), inspection.repository_snapshots, snapshot_id)
            elif item.kind == "vault":
                self._clear_vault_state()
                self._preselect_output_path(Path(item.path), vault=True)
                self.vault_query.set("")
                self.vault_extension.set("")
                if search_result is not None and search_result.member:
                    self.vault_results.insert("", "end", iid="library-match", values=(search_result.member, "", windows_app._format_size(search_result.size), ""))
                    self.vault_results_archive = Path(item.path)
                    self.vault_results.selection_set("library-match")
                    self.vault_result_count.set("1 exact filename from Library search — choose Preview or Extract when ready")
            elif item.kind == "sealed_file":
                self.apply_launch_request(windows_app.LaunchRequest("open-sealed", Path(item.path)))
            else:
                # Use the inspected format, not a misleading .db suffix.
                self.apply_launch_request(windows_app.LaunchRequest("open-archive", Path(item.path)))
            if search_result is not None and search_result.member and item.kind != "vault":
                messagebox.showinfo("Found in stored files", f"File: {search_result.member}\n\n" +
                    (f"Exact backup snapshot selected: {snapshot_id}\n" if snapshot_id else "Containing archive selected.\n") +
                    "Nothing has been extracted. Use the workspace's restore/extract controls when ready.", parent=self.root)
        self._library_task("Checking item before opening its workspace…", work, done)

    def _library_render_repository(self, path, snapshots, snapshot_id=None):
        # Do not call repository_info/list_snapshots: they perform recovery/catalogue writes.
        self.repository_path.set(str(path))
        self.repository_loaded_path = path
        self.repository_snapshots = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
        self.repository_history_snapshot_ids.clear()
        tree = self.repository_snapshot_tree
        tree.delete(*tree.get_children())
        self.repository_history_tree.delete(*self.repository_history_tree.get_children())
        for snapshot in sorted(snapshots, key=lambda value: (value.created_at_ns, value.snapshot_id), reverse=True):
            tree.insert("", "end", iid=snapshot.snapshot_id, values=(
                windows_app._format_time_ns(snapshot.created_at_ns), snapshot.label or "(no label)",
                Path(snapshot.source_path).name, f"{snapshot.file_count:,}", windows_app._format_size(snapshot.total_bytes),
                f"{snapshot.changed_file_count:,} / -{snapshot.deleted_file_count:,}", "Yes" if snapshot.pinned else "", snapshot.snapshot_id[:10]))
        self.repository_status.set(f"{len(snapshots):,} snapshot(s) · Read-only Library view. Payloads not verified; storage totals not calculated. Use Verify to check integrity.")
        self.repository_pin_button.configure(text="Pin selected")
        self.repository_result_tabs.select(0)
        if snapshot_id:
            tree.selection_set(snapshot_id)
            tree.see(snapshot_id)
            self._repository_snapshot_selected()
        self._go_to("Backups & history")
        self.status_text.set("Backup history selected — choose a snapshot and Restore when ready. Nothing restored automatically.")

    def _copy_support_details(self):
        if not self._library_guard():
            return
        windows_app.RatTrapApp._copy_support_details(self)
        self.root.clipboard_append(f"\nInterface: Library & project timeline ({SUPPORT_VERSION})")


def _library_self_test():
    """Disposable smoke test, including persistence, without touching a user's Library."""
    with tempfile.TemporaryDirectory(prefix="rat-trap-library-self-test-") as temporary:
        base = Path(temporary)
        log = diagnostics.LocalDiagnostics(base / "logs")
        root = tk.Tk()
        root.withdraw()
        try:
            app = LibraryRatTrapApp(root, diagnostic_log=log, library_path=base / "library.sqlite3")
            if app.library_store.catalog_path.exists():
                raise RuntimeError("Startup unexpectedly created a catalogue")
            project = app.library_store.create_project("Disposable sample project")
            app.library_store.add_note("A local timeline note", project_id=project.id, event_date="2026-10-20")
            app._refresh_library_view()
            app.library_project_filter.set(f"{project.name} [{project.id[:8]}]")
            app._go_to("Library")
            root.update_idletasks()
            if len(app.library_timeline_tree.get_children()) != 1:
                raise RuntimeError("Project timeline did not render its note")
            if library.LibraryStore(app.library_store.catalog_path).list_projects()[0].id != project.id:
                raise RuntimeError("Project did not persist")
            for title in app.pages:
                if not app._go_to(title):
                    raise RuntimeError("Library navigation failed")
            app.busy = True
            app._library_add_note()
            if len(app.library_store.timeline()) != 1:
                raise RuntimeError("Busy action guard failed")
            app.busy = False
        finally:
            for timer in root.tk.call("after", "info"):
                root.after_cancel(timer)
            root.destroy()
            log.close()


def _tutorial_self_test():
    # Reuse the established full five-lesson exerciser with this subclass and an
    # isolated catalogue. Give ONLY the exerciser a constructor override; do not
    # change guided_app globals (its normal-only wrappers use explicit super).
    with tempfile.TemporaryDirectory(prefix="rat-trap-library-tutorial-") as temporary:
        def factory(root, *, diagnostic_log=None):
            return LibraryRatTrapApp(root, diagnostic_log=diagnostic_log,
                                     library_path=Path(temporary) / "library.sqlite3")
        exercise = guided_app._tutorial_self_test
        isolated = types.FunctionType(exercise.__code__, {**exercise.__globals__, "GuidedRatTrapApp": factory})
        isolated()


def _store_folder_self_test():
    """Packaged workflow check with generated data and an isolated catalogue."""
    from . import gmw_tool, repository_engine
    with tempfile.TemporaryDirectory(prefix="rat-trap-store-self-test-") as temporary:
        base = Path(temporary)
        store = library.LibraryStore(base / "catalogue" / "library.sqlite3")
        project = store.create_project("Disposable storage workflow")
        source = base / "source"
        source.mkdir()
        content = source / "example.txt"
        original = b"Generated original contents\n" * 100
        content.write_bytes(original)
        archive = library_storage.store_folder(store, library_storage.StoreRequest(
            source, base / "archive.gmw", project.id))
        gmw_tool.extract_archive(archive.path, base / "archive-restored")
        if (base / "archive-restored" / "example.txt").read_bytes() != original:
            raise RuntimeError("Store-folder archive round trip failed")
        request = library_storage.StoreRequest(source, base / "versions", project.id, mode="backup")
        first = library_storage.store_folder(store, request)
        content.write_bytes(b"Generated later revision")
        second = library_storage.store_folder(store, request)
        repository_engine.restore_snapshot(first.path, first.snapshot_id, base / "older-restored")
        if ((base / "older-restored" / "example.txt").read_bytes() != original
                or content.read_bytes() != b"Generated later revision"
                or first.item.id != second.item.id):
            raise RuntimeError("Store-folder exact-version restore failed")
        root = tk.Tk()
        root.withdraw()
        log = diagnostics.LocalDiagnostics(base / "logs")
        try:
            app = LibraryRatTrapApp(root, diagnostic_log=log, library_path=store.catalog_path)
            app.library_project_filter.set(f"{project.name} [{project.id[:8]}]")
            app._go_to("Library")
            app._library_store_open()
            root.update_idletasks()
            if app.library_modes.select() != str(app.library_store_form):
                raise RuntimeError("Store-folder form did not open")
            events = [event for event in app.library_store.timeline() if event.kind == "snapshot"]
            if {event.snapshot_id for event in events} != {first.snapshot_id, second.snapshot_id}:
                raise RuntimeError("Store-folder timeline lost an exact version")
        finally:
            for timer in root.tk.call("after", "info"):
                root.after_cancel(timer)
            root.destroy()
            log.close()


def _library_search_self_test():
    """Generated data only; exercise packaged search and its Tk worker path."""
    import time
    from . import gmw_tool, repository_engine
    with tempfile.TemporaryDirectory(prefix="rat-trap-search-self-test-") as temporary:
        base = Path(temporary)
        store = library.LibraryStore(base / "catalogue" / "library.sqlite3")
        project = store.create_project("Search qualification")
        source = base / "source"
        source.mkdir()
        (source / "needle.txt").write_text("Generated search fixture", encoding="utf-8")
        for profile in ("balanced", "vault"):
            output = base / (profile + ".gmw")
            gmw_tool.compress_folder(source, output, profile=profile)
            store.register(output, project_id=project.id)
        repository = base / "versions"
        repository_engine.init_repository(repository)
        first = repository_engine.create_snapshot(repository, source, label="First")
        (source / "needle.txt").write_text("Generated later revision", encoding="utf-8")
        repository_engine.create_snapshot(repository, source, label="Second")
        store.register(repository, project_id=project.id)
        before = store.catalog_path.read_bytes()
        root = tk.Tk()
        root.withdraw()
        log = diagnostics.LocalDiagnostics(base / "logs")
        try:
            app = LibraryRatTrapApp(root, diagnostic_log=log, library_path=store.catalog_path)
            app._go_to("Library")
            app.library_modes.select(app.library_search_form)
            app.library_search_query.set("needle.txt")
            app._library_search_start()
            deadline = time.monotonic() + 60
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            hits = list(app._library_search_results.values())
            if app.busy or len(hits) != 4 or any(hit.kind != "File" for hit in hits):
                raise RuntimeError("Packaged Library search did not find all four stored versions")
            old = next(hit for hit in hits if hit.snapshot_id == first.snapshot_id)
            library_search.validate_result(store, old)
            if before != store.catalog_path.read_bytes():
                raise RuntimeError("Search unexpectedly wrote to the catalogue")
            app._library_search_clear()
            if app._library_search_results:
                raise RuntimeError("Search results were not cleared")
        finally:
            for timer in root.tk.call("after", "info"):
                root.after_cancel(timer)
            root.destroy()
            log.close()


def _library_restore_self_test():
    """Restore generated Vault data and an older backup; never use user data."""
    import hashlib
    from . import gmw_tool, repository_engine
    with tempfile.TemporaryDirectory(prefix="rat-trap-restore-self-test-") as temporary:
        base = Path(temporary)
        store = library.LibraryStore(base / "catalogue" / "library.sqlite3")
        project = store.create_project("Restore qualification")
        source = base / "source"
        (source / "nested").mkdir(parents=True)
        content = b"Generated exact older bytes\x00\xff"
        (source / "nested" / "needle.txt").write_bytes(content)
        (source / "unselected.bin").write_bytes(b"Do not restore this file")
        vault = base / "vault.gmw"
        gmw_tool.compress_folder(source, vault, profile="vault")
        vault_item = store.register(vault, project_id=project.id)
        repository = base / "versions"
        repository_engine.init_repository(repository)
        first = repository_engine.create_snapshot(repository, source, label="Older")
        (source / "nested" / "needle.txt").write_bytes(b"Later version")
        repository_engine.create_snapshot(repository, source, label="Latest")
        store.register(repository, project_id=project.id)
        hits = library_search.search_library(store, "needle.txt").results
        selected = [next(h for h in hits if h.item_id == vault_item.id),
                    next(h for h in hits if h.snapshot_id == first.snapshot_id)]
        for index, hit in enumerate(selected):
            request = library_restore.RestoreRequest(hit, base / f"restored-{index}")
            result = library_restore.restore_file(store, request)
            if (result.path.read_bytes() != content or result.sha256 != hashlib.sha256(content).hexdigest()
                    or result.event is None or result.catalogue_error or (result.destination / "unselected.bin").exists()):
                raise RuntimeError("Packaged single-file restore verification failed")
            try:
                library_restore.restore_file(store, request)
            except library.LibraryError:
                pass
            else:
                raise RuntimeError("Packaged restore accepted an existing destination")
        if len([event for event in store.timeline() if event.title == "File restored"]) != 2:
            raise RuntimeError("Packaged restore receipts missing")


def _library_health_self_test():
    """Check generated storage through the packaged Tk worker, then damage a copy."""
    import hashlib
    import time
    from . import gmw_tool, repository_engine
    with tempfile.TemporaryDirectory(prefix="rat-trap-health-self-test-") as temporary:
        base = Path(temporary)
        source = base / "source"
        source.mkdir()
        (source / "example.txt").write_bytes(b"Generated health fixture")
        store = library.LibraryStore(base / "catalogue" / "library.sqlite3")
        vault = base / "vault.gmw"
        gmw_tool.compress_folder(source, vault, profile="vault")
        vault_item = store.register(vault)
        repository = base / "versions"
        repository_engine.init_repository(repository)
        repository_engine.create_snapshot(repository, source, label="First")
        (source / "example.txt").write_bytes(b"Generated later version")
        repository_engine.create_snapshot(repository, source, label="Second")
        backup = store.register(repository)
        def fingerprint():
            return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in [vault, *repository.rglob("*")] if p.is_file()}
        before = fingerprint()
        root = tk.Tk()
        root.withdraw()
        log = diagnostics.LocalDiagnostics(base / "logs")
        previous_confirm = messagebox.askyesno
        try:
            app = LibraryRatTrapApp(root, diagnostic_log=log, library_path=store.catalog_path)
            app._go_to("Library")
            app.library_modes.select(app.library_health_form)
            messagebox.askyesno = lambda *args, **kwargs: True
            app._library_health_start()
            deadline = time.monotonic() + 90
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            results = app._library_health_results
            if app.busy or set(results) != {vault_item.id, backup.id} or any(r.status != "Verified" for r in results.values()):
                raise RuntimeError("Packaged Library health check failed")
            if before != fingerprint() or len(store.latest_health_receipts()) != 2:
                raise RuntimeError("Health check changed storage or omitted receipts")
            pack = next((repository / "packs").rglob("*.rtpack"))
            pack.write_bytes(b"Generated damaged pack")
            result = library_health.check_item(store, backup)
            if result.status != "Needs attention":
                raise RuntimeError("Damaged backup was incorrectly marked verified")
        finally:
            messagebox.askyesno = previous_confirm
            for timer in root.tk.call("after", "info"):
                root.after_cancel(timer)
            root.destroy()
            log.close()


def _backup_plans_self_test():
    """Exercise manual save and two explicit GUI runs using generated data only."""
    import time
    from . import repository_engine
    with tempfile.TemporaryDirectory(prefix="rat-trap-plans-self-test-") as temporary:
        base = Path(temporary)
        source = base / "source"
        source.mkdir()
        (source / "example.txt").write_bytes(b"Generated first version")
        target = base / "backups"
        root = tk.Tk()
        root.withdraw()
        log = diagnostics.LocalDiagnostics(base / "logs")
        confirm, warning = messagebox.askyesno, messagebox.showwarning
        def fail_warning(*args, **kwargs):
            raise RuntimeError(str(args))
        try:
            messagebox.askyesno = lambda *args, **kwargs: True
            messagebox.showwarning = fail_warning
            app = LibraryRatTrapApp(root, diagnostic_log=log, library_path=base / "catalog" / "library.sqlite3")
            project = app.library_store.create_project("Generated plan project")
            app._refresh_library_view()
            app.library_plan_project.set(f"{project.name} [{project.id[:8]}]")
            app.library_plan_name.set("Generated manual plan")
            app.library_plan_source.set(str(source))
            app.library_plan_destination.set(str(target))
            app._go_to("Library")
            app.library_modes.select(app.library_plans_form)
            def wait_idle():
                deadline = time.monotonic() + 90
                while app.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                if app.busy:
                    raise RuntimeError("Manual plan worker did not finish")
            app._library_plan_save()
            wait_idle()
            plans = library_plans.list_plans(app.library_store)
            if len(plans) != 1 or target.exists():
                raise RuntimeError("Saving settings unexpectedly ran a backup")
            app.library_plans_tree.selection_set(plans[0].id)
            app._library_plan_run()
            wait_idle()
            first = library_plans.get_plan(app.library_store, plans[0].id)
            if first.last_status != "Succeeded":
                raise RuntimeError(first.last_detail)
            (source / "example.txt").write_bytes(b"Generated second version")
            app._library_plan_run()
            wait_idle()
            second = library_plans.get_plan(app.library_store, first.id)
            if second.last_status != "Succeeded" or first.last_success_snapshot == second.last_success_snapshot:
                raise RuntimeError("Repeated manual plan did not create another version")
            restored = base / "old-copy"
            repository_engine.restore_snapshot(target, first.last_success_snapshot, restored)
            if ((restored / "example.txt").read_bytes() != b"Generated first version"
                    or (source / "example.txt").read_bytes() != b"Generated second version"):
                raise RuntimeError("Manual plan older-version restore failed")
            receipts = [event for event in app.library_store.timeline() if event.title == "Backup plan run"]
            if len(receipts) != 2:
                raise RuntimeError("Missing manual-run timeline receipts")
        finally:
            messagebox.askyesno, messagebox.showwarning = confirm, warning
            for timer in root.tk.call("after", "info"):
                root.after_cancel(timer)
            root.destroy()
            log.close()


def main():
    if sys.argv[1:] == ["--backup-plans-self-test"]:
        _backup_plans_self_test()
        return
    if sys.argv[1:] == ["--library-health-self-test"]:
        _library_health_self_test()
        return
    if sys.argv[1:] == ["--library-restore-self-test"]:
        _library_restore_self_test()
        return
    if sys.argv[1:] == ["--library-search-self-test"]:
        _library_search_self_test()
        return
    if sys.argv[1:] == ["--store-folder-self-test"]:
        _store_folder_self_test()
        return
    if sys.argv[1:] in (["--ui-self-test"], ["--library-self-test"]):
        _library_self_test()
        return
    if sys.argv[1:] == ["--tutorial-self-test"]:
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
        app = LibraryRatTrapApp(root, diagnostic_log=log)
        if request is not None:
            app.apply_launch_request(request)
        root.mainloop()
    except Exception as exc:
        reference = log.record_exception("app.startup.failed", exc, details={"component": "windows_ui", "stage": "startup", "status": "failed"})
        if root is None:
            root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Rat-Trap", f"The Library preview could not start.\n\nError reference: {reference}", parent=root)
        root.destroy()
    finally:
        log.close()


if __name__ == "__main__":
    main()
