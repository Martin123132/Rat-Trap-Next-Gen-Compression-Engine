"""Desktop Preview 2: session-only selection, honest progress and result actions.

The existing engine, credential dialogs and worker lifecycle are inherited.
Preview 1 stays separately runnable and its source is not rewritten.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import desktop_app, diagnostics, sealed_file, windows_app


PREVIEW_LABEL = "Desktop Preview 2"


def normalize_path_text(text: str) -> str:
    value = text.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class TaskContext:
    operation: str
    path: Path | None


@dataclass(frozen=True)
class CompletedOutput:
    path: Path
    kind: str
    title: str
    summary: str


def reveal_in_folder(path: Path) -> None:
    """Open only an existing directory, never execute the completed output."""
    target = Path(path).absolute()
    if not target.exists():
        raise FileNotFoundError("The output has moved or is no longer available")
    folder = target if target.is_dir() else target.parent
    if not folder.is_dir():
        raise NotADirectoryError("The containing folder is unavailable")
    if os.name != "nt":
        raise OSError("Show in folder is available in the Windows preview")
    os.startfile(str(folder), "explore")


class DesktopPreview2App(desktop_app.DesktopPreviewApp):
    def __init__(self, root: tk.Tk, *, diagnostic_log=None) -> None:
        self.last_output: CompletedOutput | None = None
        self._picker_directory: Path | None = None
        self._activity_token: object | None = None
        self._activity_after_id: str | None = None
        self._activity_started = 0.0
        self._activity_frozen_at: float | None = None
        self._activity_outcome = "idle"
        super().__init__(root, diagnostic_log=diagnostic_log)

    def _build_ui(self) -> None:
        super()._build_ui()
        self.root.title(f"Rat-Trap — {PREVIEW_LABEL}")
        self._update_preview_labels(self.root)
        footer = self.progress.master
        # Reserve footer space before the flexible workspace; its canvas can
        # scroll, whereas result buttons must never end up below the window.
        footer.pack_configure(side="bottom", before=self.tabs)
        self.activity_title = tk.StringVar(value="Ready for your next task")
        self.activity_elapsed = tk.StringVar(value="")
        self.activity_hint = tk.StringVar(value="Choose a task above. Your files are never opened automatically.")
        self.result_path = tk.StringVar()
        self.result_summary = tk.StringVar()
        self.result_title = tk.StringVar()
        self.activity_stage = tk.StringVar(value=self.status_text.get())
        # Preserve the inherited status StringVar and Progressbar used by the
        # proven worker lifecycle; only their presentation changes here.
        status_label = next(widget for widget in footer.winfo_children() if isinstance(widget, ttk.Label))
        status_label.configure(textvariable=self.activity_stage)
        self.status_text.trace_add("write", self._sync_activity_stage)
        status_label.grid_configure(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.progress.grid_configure(row=2, column=0, columnspan=2, sticky="ew", padx=0, pady=(8, 6))
        ttk.Label(footer, textvariable=self.activity_title, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.activity_elapsed, style="Subtitle.TLabel").grid(row=0, column=1, sticky="e", padx=(10, 0))
        hint = ttk.Label(footer, textvariable=self.activity_hint, style="Subtitle.TLabel", wraplength=650)
        hint.grid(row=3, column=0, columnspan=2, sticky="ew")
        self._progress_detail_widgets = (status_label, self.progress, hint)
        self.completion_frame = ttk.Frame(footer, padding=(0, 10, 0, 0))
        self.completion_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.completion_frame.columnconfigure(0, weight=1)
        summary = ttk.Label(self.completion_frame, textvariable=self.result_summary, style="Subtitle.TLabel", wraplength=650)
        summary.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        self.result_path_entry = ttk.Entry(self.completion_frame, textvariable=self.result_path, state="readonly")
        self.result_path_entry.grid(row=2, column=0, sticky="ew")
        actions = ttk.Frame(self.completion_frame)
        actions.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.open_result_button = ttk.Button(actions, text="Open archive", command=self._open_result, state="disabled")
        self.open_result_button.pack(side="left")
        self.reveal_result_button = ttk.Button(actions, text="Show in folder", command=self._show_result_folder, state="disabled")
        self.reveal_result_button.pack(side="left", padx=(8, 0))
        self.action_buttons.extend((self.open_result_button, self.reveal_result_button))
        self.completion_frame.grid_remove()
        footer.bind("<Configure>", lambda event: self._wrap_activity(event.width, status_label, hint, summary), add="+")
        ttk.Label(
            self.pages["Create archive"],
            text="Tip: paste a path copied from File Explorer. Surrounding double quotes are removed when you leave the field.",
            style="Subtitle.TLabel", wraplength=650,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(18, 0))
        # This new label is added after Preview 1 prepares responsive labels.
        self.page_scrollers["Create archive"].prepare()

    @staticmethod
    def _wrap_activity(width: int, *labels: ttk.Label) -> None:
        for label in labels:
            label.configure(wraplength=max(180, width - 30))

    def _sync_activity_stage(self, *_args: object) -> None:
        reported = " ".join(self.status_text.get().split())
        self.activity_stage.set(reported if len(reported) <= 100 else reported[:97] + "…")

    def _update_preview_labels(self, widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            if isinstance(child, ttk.Label):
                text = str(child.cget("text"))
                if desktop_app.PREVIEW_LABEL in text:
                    child.configure(text=text.replace(desktop_app.PREVIEW_LABEL, PREVIEW_LABEL))
            self._update_preview_labels(child)

    def _copy_support_details(self) -> None:
        windows_app.RatTrapApp._copy_support_details(self)
        self.root.clipboard_append(f"\nInterface: {PREVIEW_LABEL} (5.7.0-desktop-preview.2)")

    def _path_row(self, parent, row, label, variable, command) -> None:
        super()._path_row(parent, row, label, variable, command)
        self.path_entries[str(variable)].bind(
            "<FocusOut>", lambda _event, value=variable: self._normalize_path_variable(value), add="+",
        )

    def _normalize_path_variable(self, variable: tk.StringVar) -> None:
        if not self.busy:
            normalized = normalize_path_text(variable.get())
            if normalized != variable.get():
                variable.set(normalized)

    def _prepare_operation_paths(self, *names: str) -> bool:
        if self.busy:
            return False
        for name in names:
            self._normalize_path_variable(getattr(self, name))
        return True

    def _start_create(self) -> None:
        if self._prepare_operation_paths("source_folder", "create_archive"):
            super()._start_create()

    def _start_extract(self) -> None:
        if self._prepare_operation_paths("extract_archive", "extract_folder"):
            super()._start_extract()

    def _start_seal_file(self) -> None:
        if self._prepare_operation_paths("seal_source", "seal_output"):
            super()._start_seal_file()

    def _start_unseal_file(self) -> None:
        if self._prepare_operation_paths("unseal_source", "unseal_destination"):
            super()._start_unseal_file()

    def _picker_initial_directory(self, current: str = "") -> str | None:
        """Memory for ordinary file pickers only; never used by key dialogs."""
        candidates = []
        value = normalize_path_text(current)
        if value:
            candidate = Path(value)
            candidates.extend((candidate, candidate.parent))
        if self._picker_directory is not None:
            candidates.append(self._picker_directory)
        for candidate in candidates:
            try:
                if candidate.is_dir():
                    return str(candidate.absolute())
            except OSError:
                continue
        return None

    def _remember_selection(self, selected: str, *, directory: bool = False) -> Path:
        path = Path(normalize_path_text(selected)).absolute()
        self._picker_directory = path if directory else path.parent
        return path

    def _choose_source(self) -> None:
        if self.busy:
            return
        selected = filedialog.askdirectory(parent=self.root, title="Choose the folder to compress", mustexist=True,
                                           initialdir=self._picker_initial_directory(self.source_folder.get()))
        if not selected:
            return
        path = self._remember_selection(selected, directory=True)
        destination = desktop_app.updated_archive_destination(
            normalize_path_text(self.source_folder.get()), str(path), normalize_path_text(self.create_archive.get()),
            windows_app.PROFILE_OPTIONS[self.profile_label.get()],
        )
        self.source_folder.set(str(path))
        self.create_archive.set(destination)
        self.path_entries[str(self.source_folder)].focus_set()

    def _choose_create_archive(self) -> None:
        if self.busy:
            return
        current = normalize_path_text(self.create_archive.get())
        source = normalize_path_text(self.source_folder.get())
        selected = filedialog.asksaveasfilename(
            parent=self.root, title="Save Rat-Trap archive",
            initialdir=self._picker_initial_directory(current or (str(Path(source).parent) if source else "")),
            initialfile=Path(current).name if current else (self._suggested_output_name(Path(source)) if source else "archive.gmw"),
            defaultextension=".gmw", filetypes=windows_app.ARCHIVE_TYPES,
        )
        if selected:
            self.create_archive.set(str(self._remember_selection(selected)))

    def _open_existing(self, *, restore: bool = False) -> None:
        if self.busy:
            return
        selected = filedialog.askopenfilename(
            parent=self.root, title="Open a Rat-Trap archive or Sealed File",
            initialdir=self._picker_initial_directory(),
            filetypes=[("Rat-Trap files", "*.gmw *.rtsf *.db"), ("All files", "*.*")],
        )
        if not selected:
            return
        path = Path(normalize_path_text(selected)).absolute()
        if path.suffix.lower() not in {".gmw", ".rtsf", ".db"}:
            messagebox.showwarning("Rat-Trap", "Choose a .gmw archive, .rtsf Sealed File or .db Vault. Recovery keys are not archives.", parent=self.root)
            return
        self._remember_selection(str(path))
        self._preselect_output_path(path, restore=restore)

    def _preselect_output_path(self, path: Path, *, restore: bool = False, vault: bool = False) -> None:
        if self.busy:
            return
        suffix = path.suffix.lower()
        if suffix == ".rtsf":
            self.apply_launch_request(windows_app.LaunchRequest("open-sealed", path))
        elif suffix == ".db" or vault:
            self._go_to("Search Vault")
            self.vault_archive.set(str(path))
            self.data_archive.set(str(path))
            self.status_text.set("Vault selected — choose Search when ready; no files have been opened")
        elif suffix == ".gmw" and restore:
            self._go_to("Extract archive")
            self._set_extract_selection(path)
        elif suffix == ".gmw":
            self.apply_launch_request(windows_app.LaunchRequest("open-archive", path))

    def _set_extract_selection(self, path: Path) -> None:
        previous = normalize_path_text(self.extract_archive.get())
        current = normalize_path_text(self.extract_folder.get())
        automatic = not current or (previous and Path(current) == Path(previous).parent / f"{Path(previous).stem}_extracted")
        self.extract_archive.set(str(path))
        if automatic:
            self.extract_folder.set(str(path.parent / f"{path.stem}_extracted"))
        self.status_text.set("Archive selected — choose Extract when ready")

    def _choose_extract_archive(self) -> None:
        if self.busy:
            return
        selected = filedialog.askopenfilename(parent=self.root, title="Choose an archive to restore",
                                             initialdir=self._picker_initial_directory(self.extract_archive.get()),
                                             filetypes=windows_app.ARCHIVE_TYPES)
        if selected:
            self._set_extract_selection(self._remember_selection(selected))

    def _choose_extract_folder(self) -> None:
        if self.busy:
            return
        selected = filedialog.askdirectory(parent=self.root, title="Choose where to restore files",
                                           initialdir=self._picker_initial_directory(self.extract_folder.get()))
        if selected:
            self.extract_folder.set(str(self._remember_selection(selected, directory=True)))

    def _choose_seal_source(self) -> None:
        if self.busy:
            return
        selected = filedialog.askopenfilename(parent=self.root, title="Choose the file to protect",
                                             initialdir=self._picker_initial_directory(self.seal_source.get()))
        if not selected:
            return
        previous = normalize_path_text(self.seal_source.get())
        current = normalize_path_text(self.seal_output.get())
        path = self._remember_selection(selected)
        automatic = not current or (previous and Path(current).parent == Path(previous).parent
                                     and windows_app._uses_opaque_sealed_name(Path(current)))
        self.seal_source.set(str(path))
        if automatic:
            self.seal_output.set(str(path.parent / sealed_file.default_sealed_name()))

    def _capture_task_context(self, label: str) -> TaskContext:
        operation = windows_app._task_operation_code(label)
        output_variables = {"archive_create": "create_archive", "archive_extract": "extract_folder",
                            "sealed_create": "seal_output", "sealed_restore": "unseal_destination"}
        name = output_variables.get(operation)
        value = normalize_path_text(getattr(self, name).get()) if name else ""
        return TaskContext(operation, Path(value).absolute() if value else None)

    def _run_task(self, label, work, done) -> None:
        if self.busy:
            return
        self._stop_activity_clock(self._activity_token)
        token = object()
        self._activity_token = token
        self._activity_started = time.monotonic()
        self._activity_frozen_at = None
        self._activity_outcome = "working"
        context = self._capture_task_context(label)
        self._clear_completion()
        self.activity_title.set("Working")
        self.activity_elapsed.set("Elapsed 00:00")
        self.activity_hint.set("Elapsed time only; percentage and time remaining are not available.")

        def completed(result):
            # These dialogs include recovery-key locations and security warnings.
            done(result)
            # Some inherited callbacks start another task (e.g. backup refresh).
            if token is not self._activity_token:
                return
            if isinstance(result, BaseException):
                self._activity_outcome = "review"
                self.activity_title.set("Needs review")
                self.activity_hint.set("Review the operation's message before continuing.")
                return
            output = self._completed_output(context, result)
            self._activity_outcome = "finished"
            self.activity_title.set(output.title if output else "Task finished — review the result")
            self.activity_hint.set("Choose what to do next. Nothing opens automatically." if output else "Review the workspace result and any reported warnings.")
            if output is not None:
                self._publish_completion(output)

        super()._run_task(label, work, completed)
        if token is not self._activity_token:
            return
        if self.busy:
            self._tick_activity(token)
        else:
            self._stop_activity_clock(token)
            self.activity_title.set("Could not start — see the error message")

    def _tick_activity(self, token: object) -> None:
        if token is not self._activity_token or self._closing:
            return
        self._activity_after_id = None
        if not self.busy:
            if self._activity_outcome == "working":
                self._mark_activity_failure(token)
            return
        try:
            self.activity_elapsed.set(f"Elapsed {format_elapsed(time.monotonic() - self._activity_started)}")
            if self._task_monitor_failed:
                self.activity_hint.set("Progress updates were interrupted. Work may still be running; keep Rat-Trap open.")
            self._activity_after_id = self.root.after(500, lambda current=token: self._tick_activity(current))
        except tk.TclError:
            # An optional display timer must not stop or claim to cancel a worker.
            self._activity_after_id = None

    def _stop_activity_clock(self, token: object | None) -> None:
        if token is not self._activity_token:
            return
        if self._activity_after_id is not None:
            try:
                self.root.after_cancel(self._activity_after_id)
            except tk.TclError:
                pass
            self._activity_after_id = None
        if self._activity_started and hasattr(self, "activity_elapsed"):
            try:
                if self._activity_frozen_at is None:
                    self._activity_frozen_at = time.monotonic()
                self.activity_elapsed.set(f"Elapsed {format_elapsed(self._activity_frozen_at - self._activity_started)}")
            except tk.TclError:
                pass

    def _finish_task(self, result, done, error) -> None:
        token = self._activity_token
        self._stop_activity_clock(token)  # Excludes time spent reading completion dialogs.
        try:
            super()._finish_task(result, done, error)
        finally:
            if token is self._activity_token and not self.busy and self._activity_outcome == "working":
                self._mark_activity_failure(token)

    def _fail_task_setup(self, event, exception, *, stage) -> None:
        token = self._activity_token
        self._stop_activity_clock(token)
        try:
            super()._fail_task_setup(event, exception, stage=stage)
        finally:
            if token is self._activity_token and not self.busy:
                self._mark_activity_failure(token)

    def _mark_activity_failure(self, token: object | None) -> None:
        if token is not self._activity_token:
            return
        self._stop_activity_clock(token)
        self._activity_outcome = "review"
        self.activity_title.set("Needs attention")
        self.activity_hint.set("No completed output recorded. Review the error message before trying again.")

    def _completed_output(self, context: TaskContext, result: object) -> CompletedOutput | None:
        path = context.path
        if path is None:
            return None
        if context.operation == "archive_create" and isinstance(result, windows_app.gmw_tool.Metadata):
            vault = result.format == "GMW-VAULT-1"
            protection = "Encrypted archive" if result.encrypted else "Not encrypted"
            summary = f"{result.file_count:,} files · Original size {windows_app._format_size(result.total_bytes)} · {protection}"
            return CompletedOutput(path, "vault" if vault else "archive", "Vault ready" if vault else "Archive ready", summary)
        if context.operation == "archive_extract" and isinstance(result, windows_app.gmw_tool.Metadata):
            return CompletedOutput(path, "folder", "Files restored", f"{result.file_count:,} files restored. The output may contain unencrypted data.")
        if context.operation == "sealed_create" and isinstance(result, sealed_file.SealResult):
            return CompletedOutput(Path(result.sealed_file.path).absolute(), "sealed", "Sealed File ready",
                                   "Encrypted and verified. Keep its recovery key separate; your original file is retained.")
        if context.operation == "sealed_restore" and isinstance(result, sealed_file.UnsealResult):
            return CompletedOutput(Path(result.output).absolute(), "file", "File restored",
                                   "Plaintext copy restored and verified. Show in folder does not launch this file.")
        return None

    @staticmethod
    def _can_open_output(output: CompletedOutput) -> bool:
        allowed = {"archive": {".gmw"}, "vault": {".gmw", ".db"}, "sealed": {".rtsf"}}
        return output.path.suffix.lower() in allowed.get(output.kind, set())

    def _publish_completion(self, output: CompletedOutput) -> None:
        self.last_output = output
        self.result_title.set(output.title)
        self.result_path.set(str(output.path))
        self.result_summary.set(output.summary)
        self.open_result_button.configure(state="normal" if self._can_open_output(output) else "disabled",
                                          text="Open Sealed File" if output.kind == "sealed" else "Open archive")
        self.reveal_result_button.configure(state="normal")
        for widget in self._progress_detail_widgets:
            widget.grid_remove()
        self.completion_frame.grid()

    def _clear_completion(self) -> None:
        self.last_output = None
        self.result_title.set("")
        self.result_path.set("")
        self.result_summary.set("")
        self.open_result_button.configure(state="disabled")
        self.reveal_result_button.configure(state="disabled")
        self.completion_frame.grid_remove()
        for widget in self._progress_detail_widgets:
            widget.grid()

    def _available_output(self) -> CompletedOutput | None:
        if self.busy or self.last_output is None:
            return None
        output = self.last_output
        try:
            available = output.path.is_dir() if output.kind == "folder" else output.path.is_file()
        except OSError:
            available = False
        if not available:
            messagebox.showwarning("Rat-Trap", "This output has moved or is no longer available. Choose its new location with Open Rat-Trap file.", parent=self.root)
            return None
        return output

    def _open_result(self) -> None:
        output = self._available_output()
        if output is not None and self._can_open_output(output):
            self._preselect_output_path(output.path, vault=output.kind == "vault")

    def _show_result_folder(self) -> None:
        output = self._available_output()
        if output is None:
            return
        try:
            reveal_in_folder(output.path)
        except OSError:
            messagebox.showwarning("Rat-Trap", "Windows could not open the containing folder. The output path is shown above so you can find it manually.", parent=self.root)

    def _root_destroyed(self, event: object) -> None:
        if getattr(event, "widget", None) is self.root:
            self._stop_activity_clock(self._activity_token)
            self._activity_token = None
        super()._root_destroyed(event)


def _ui_self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="rat-trap-preview2-ui-test-") as temporary:
        log = diagnostics.LocalDiagnostics(Path(temporary))
        root = tk.Tk()
        root.withdraw()
        try:
            app = DesktopPreview2App(root, diagnostic_log=log)
            root.update_idletasks()
            if set(app.pages) != set(desktop_app.WORKSPACE_NAMES) or app.last_output is not None:
                raise RuntimeError("Preview 2 workspace or initial output state is invalid")
            for title in app.pages:
                if not app._go_to(title):
                    raise RuntimeError("Preview 2 navigation failed")
            if str(app.open_result_button.cget("state")) != "disabled":
                raise RuntimeError("Preview 2 enabled an action without an output")
            app.busy = True
            if app._go_to("Home"):
                raise RuntimeError("Preview 2 permitted navigation during work")
            app.busy = False
        finally:
            root.destroy()
            log.close()


def main() -> None:
    if sys.argv[1:] == ["--ui-self-test"]:
        _ui_self_test()
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
        app = DesktopPreview2App(root, diagnostic_log=log)
        if request is not None:
            app.apply_launch_request(request)
        root.mainloop()
    except Exception as exc:
        reference = log.record_exception("app.startup.failed", exc,
                                         details={"component": "windows_ui", "stage": "startup", "status": "failed"})
        if root is None:
            root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Rat-Trap", f"The desktop preview could not start.\n\nError reference: {reference}", parent=root)
        root.destroy()
    finally:
        log.close()


if __name__ == "__main__":
    main()
