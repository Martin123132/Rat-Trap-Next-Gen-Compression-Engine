"""Opt-in desktop preview; the frozen 5.7.0 application remains unchanged.

This module changes presentation and safe UI preselection, not archive formats,
compression, encryption, recovery, or the background-operation lifecycle.
"""

from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import diagnostics, windows_app


PREVIEW_LABEL = "Desktop Preview 1"
COLORS = {
    "background": "#F2F5F5", "surface": "#FFFFFF", "ink": "#172E36",
    "muted": "#536971", "line": "#D8E1E3", "accent": "#176C60",
    "accent_hover": "#10574D", "sidebar": "#142C34", "sidebar_hover": "#203E47",
    "sidebar_text": "#D6E4E6", "highlight": "#DDF1D3",
}
WORKSPACE_NAMES = {
    "Home": "Home", "Create archive": "Compress a folder",
    "Secure files": "Protect files", "Extract archive": "Restore files",
    "Backups & history": "Backups & history", "Search Vault": "Search a Vault",
    "Data Tables": "Data tables", "Inspect / export": "Inspect & export",
    "About": "About & support",
}


def suggested_archive_path(source: Path, profile: str) -> Path:
    suffix = ".vault.gmw" if profile == "vault" else ".gmw"
    return source.parent / f"{source.name}{suffix}"


def updated_archive_destination(
    previous_source: str, selected_source: str, current_destination: str, profile: str,
) -> str:
    """Follow changed sources only for automatic destinations; never scan files."""
    if not selected_source.strip():
        return current_destination
    automatic = not current_destination.strip()
    if previous_source.strip() and not automatic:
        previous = Path(previous_source)
        automatic = Path(current_destination) in {
            suggested_archive_path(previous, "balanced"),
            suggested_archive_path(previous, "vault"),
        }
    return (
        str(suggested_archive_path(Path(selected_source), profile))
        if automatic else current_destination
    )


class ScrollPage(ttk.Frame):
    """A workspace with overflow access, including on small/high-DPI displays."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="Surface.TFrame")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=COLORS["surface"], highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.vertical.grid(row=0, column=1, sticky="ns")
        self.horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set)
        self.content = ttk.Frame(self.canvas, padding=(28, 24), style="Surface.TFrame")
        self._item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self._labels: list[tuple[ttk.Label, int]] = []
        self.canvas.bind("<Configure>", self._layout, add="+")
        self.content.bind("<Configure>", self._layout, add="+")

    def prepare(self) -> None:
        def visit(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label):
                    text = str(child.cget("text"))
                    original = int(child.cget("wraplength") or 0)
                    if original or len(text) > 65:
                        self._labels.append((child, original or 820))
                visit(child)
        visit(self.content)
        self._layout()

    def _layout(self, _event=None) -> None:
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        for label, maximum in self._labels:
            # Cards supply a narrower original limit, which is never widened.
            target = min(maximum, max(240, width - 70))
            if int(label.cget("wraplength") or 0) != target:
                label.configure(wraplength=target)
        self.canvas.itemconfigure(
            self._item,
            width=max(width, self.content.winfo_reqwidth()),
            height=max(height, self.content.winfo_reqheight()),
        )
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


class WorkspaceStack(ttk.Frame):
    """Small notebook-compatible selector that accepts the actual content frame."""

    def __init__(self, parent: tk.Misc, on_selected) -> None:
        super().__init__(parent, style="Surface.TFrame")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._pages: dict[str, tuple[str, ScrollPage]] = {}
        self._selected = ""
        self._on_selected = on_selected

    def add_page(self, title: str, page: ScrollPage) -> None:
        self._pages[str(page.content)] = (title, page)
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()

    def tabs(self) -> tuple[str, ...]:
        return tuple(self._pages)

    def select(self, page=None) -> str:
        if page is None:
            return self._selected
        key = str(page)
        title, container = self._pages[key]
        if self._selected:
            self._pages[self._selected][1].grid_remove()
        container.grid()
        self._selected = key
        self._on_selected(title)
        return key


class DesktopPreviewApp(windows_app.RatTrapApp):
    def _configure_style(self) -> None:
        self.scale = max(0.8, float(self.root.tk.call("tk", "scaling")) / (96 / 72))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=COLORS["surface"], foreground=COLORS["ink"])
        style.configure("TFrame", background=COLORS["surface"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Background.TFrame", background=COLORS["background"])
        style.configure("TLabel", background=COLORS["surface"], foreground=COLORS["ink"])
        style.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Subtitle.TLabel", foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("Eyebrow.TLabel", foreground=COLORS["accent"], font=("Segoe UI", 9, "bold"))
        style.configure("TButton", padding=(12, 8), background="#EEF3F3", borderwidth=1,
                        bordercolor=COLORS["line"], focuscolor=COLORS["accent"])
        style.map("TButton", background=[("active", "#E1EBE9"), ("disabled", "#F0F3F3")],
                  foreground=[("disabled", "#78868B")])
        style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 11),
                        background=COLORS["accent"], foreground="white", borderwidth=0,
                        focuscolor="#DDF1D3")
        style.map("Action.TButton", background=[("disabled", "#DCE5E3"), ("active", COLORS["accent_hover"])],
                  foreground=[("disabled", "#687B76"), ("!disabled", "white")])
        style.configure("TEntry", padding=8, fieldbackground="white", bordercolor=COLORS["line"])
        style.configure("TCombobox", padding=7, fieldbackground="white", arrowsize=14)
        style.map("TCombobox", fieldbackground=[("readonly", "white")])
        style.configure("TCheckbutton", padding=(0, 5), background="white")
        style.configure("TNotebook", borderwidth=0, background="white")
        style.configure("TNotebook.Tab", padding=(12, 8))
        style.map("TNotebook.Tab", background=[("selected", COLORS["highlight"])])
        style.configure("Treeview", rowheight=int(29 * self.scale), fieldbackground="white", background="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=8)
        style.map("Treeview", background=[("selected", COLORS["accent"])], foreground=[("selected", "white")])
        style.configure("Horizontal.TProgressbar", background=COLORS["accent"], troughcolor="#E4ECEA")
        style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
        style.configure("Sidebar.TLabel", background=COLORS["sidebar"], foreground=COLORS["sidebar_text"])
        style.configure("Brand.TLabel", background=COLORS["sidebar"], foreground="white", font=("Segoe UI", 22, "bold"))
        style.configure("SidebarNote.TLabel", background=COLORS["sidebar"], foreground="#9CB7BD", font=("Segoe UI", 9))
        style.configure("Sidebar.Vertical.TScrollbar", background=COLORS["sidebar_hover"],
                        troughcolor=COLORS["sidebar"], arrowcolor=COLORS["sidebar_text"], borderwidth=0)
        for name, background, foreground in (
            ("Nav.TButton", COLORS["sidebar"], COLORS["sidebar_text"]),
            ("Selected.Nav.TButton", COLORS["highlight"], COLORS["ink"]),
        ):
            style.configure(name, anchor="w", padding=(14, 11), background=background,
                            foreground=foreground, borderwidth=0, focuscolor="#75AFA3")
            style.map(name, background=[("disabled", COLORS["sidebar"]), ("active", COLORS["sidebar_hover"])],
                      foreground=[("disabled", "#6D8A91"), ("active", "white")])

    def _build_ui(self) -> None:
        self.root.title(f"Rat-Trap — {PREVIEW_LABEL}")
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{min(screen_w - 60, int(1220 * self.scale))}x{min(screen_h - 90, int(840 * self.scale))}")
        self.root.minsize(min(screen_w - 60, 960), min(screen_h - 90, 640))
        self.root.configure(background=COLORS["background"])
        self.pages: dict[str, ttk.Frame] = {}
        self.page_scrollers: dict[str, ScrollPage] = {}
        self.path_entries: dict[str, ttk.Entry] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.workspace_title = tk.StringVar(value="Home")

        shell = ttk.Frame(self.root, style="Background.TFrame")
        shell.pack(fill="both", expand=True)
        sidebar = ttk.Frame(shell, width=int(220 * self.scale), padding=(16, 25), style="Sidebar.TFrame")
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="Rat-Trap", style="Brand.TLabel").pack(anchor="w", padx=10)
        ttk.Label(sidebar, text="YOUR FILES. IN ORDER.", style="SidebarNote.TLabel").pack(anchor="w", padx=11, pady=(3, 26))
        ttk.Label(sidebar, text="TWO HANDS\nNETWORK LTD", style="SidebarNote.TLabel").pack(side="bottom", anchor="w", padx=11, pady=(10, 0))
        ttk.Label(sidebar, text="Desktop Preview 1\n5.7.0 engine · local files", style="SidebarNote.TLabel").pack(side="bottom", anchor="w", padx=11, pady=(0, 14))
        navigation = ttk.Frame(sidebar, style="Sidebar.TFrame")
        navigation.pack(fill="both", expand=True)
        self._sidebar_canvas = tk.Canvas(navigation, background=COLORS["sidebar"], highlightthickness=0, width=1)
        self._sidebar_canvas.pack(side="left", fill="both", expand=True)
        nav_scroll = ttk.Scrollbar(navigation, orient="vertical", command=self._sidebar_canvas.yview,
                                  style="Sidebar.Vertical.TScrollbar")
        nav_scroll.pack(side="right", fill="y")
        self._sidebar_canvas.configure(yscrollcommand=nav_scroll.set)
        self._nav_container = ttk.Frame(self._sidebar_canvas, style="Sidebar.TFrame")
        nav_item = self._sidebar_canvas.create_window(0, 0, window=self._nav_container, anchor="nw")
        self._sidebar_canvas.bind("<Configure>", lambda event: self._sidebar_canvas.itemconfigure(nav_item, width=event.width), add="+")
        self._nav_container.bind("<Configure>", lambda _event: self._sidebar_canvas.configure(scrollregion=self._sidebar_canvas.bbox("all")), add="+")

        main = ttk.Frame(shell, padding=(20, 16, 20, 12), style="Background.TFrame")
        main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(main, padding=(16, 10))
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, textvariable=self.workspace_title, font=("Segoe UI", 12, "bold")).pack(side="left")
        open_button = ttk.Button(top, text="Open Rat-Trap file…", command=self._open_existing)
        open_button.pack(side="right")
        self.action_buttons.append(open_button)
        self.tabs = WorkspaceStack(main, self._workspace_selected)
        self.tabs.pack(fill="both", expand=True)

        self._build_home()
        self._build_create_tab()
        self._build_secure_files_tab()
        self._build_extract_tab()
        self._build_repository_tab()
        self._build_vault_tab()
        self._build_data_tab()
        self._build_inspect_tab()
        self._build_about_tab()
        for page in self.page_scrollers.values():
            page.prepare()
        self._style_text_widgets(self.tabs)

        footer = ttk.Frame(main, padding=(12, 8))
        footer.pack(fill="x", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self.status_text = tk.StringVar(value="Ready — choose a task to get started")
        ttk.Label(footer, textvariable=self.status_text, style="Subtitle.TLabel", wraplength=590).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.root.bind("<Control-o>", self._open_shortcut, add="+")
        self.root.bind("<Control-Key-1>", lambda _event: self._shortcut_page("Home"), add="+")
        self.root.bind("<MouseWheel>", self._scroll_page, add="+")
        self.tabs.select(self.pages["Home"])

    def _new_tab(self, title: str) -> ttk.Frame:
        page = ScrollPage(self.tabs)
        self.pages[title] = page.content
        self.page_scrollers[title] = page
        self.tabs.add_page(title, page)
        page.content.columnconfigure(1, weight=1)
        if title in {"Backups & history", "About"}:
            ttk.Separator(self._nav_container).pack(fill="x", pady=12)
        button = ttk.Button(self._nav_container, text=WORKSPACE_NAMES[title],
                            style="Nav.TButton", command=lambda current=title: self._go_to(current))
        button.pack(fill="x", pady=2)
        self.nav_buttons[title] = button
        self.action_buttons.append(button)
        button.bind("<FocusIn>", lambda _event, current=button: self._show_nav_button(current), add="+")
        return page.content

    def _show_nav_button(self, button: ttk.Button) -> None:
        self._sidebar_canvas.update_idletasks()
        top = button.winfo_y()
        bottom = top + button.winfo_height()
        visible_top = self._sidebar_canvas.canvasy(0)
        height = self._sidebar_canvas.winfo_height()
        total = max(1, self._nav_container.winfo_height())
        if top < visible_top:
            self._sidebar_canvas.yview_moveto(top / total)
        elif bottom > visible_top + height:
            self._sidebar_canvas.yview_moveto(max(0, bottom - height) / total)

    def _workspace_selected(self, title: str) -> None:
        self.workspace_title.set(WORKSPACE_NAMES[title])
        for name, button in self.nav_buttons.items():
            button.configure(style="Selected.Nav.TButton" if name == title else "Nav.TButton")
        if title in self.nav_buttons:
            self._show_nav_button(self.nav_buttons[title])

    def _go_to(self, title: str) -> bool:
        if self.busy:
            return False
        self.tabs.select(self.pages[title])
        # Keyboard users land in the chosen workspace, not behind a hidden page.
        self.pages[title].focus_set()
        return True

    def _shortcut_page(self, title: str) -> str:
        self._go_to(title)
        return "break"

    def _open_shortcut(self, _event=None) -> str:
        self._open_existing()
        return "break"

    def _build_home(self) -> None:
        tab = self._new_tab("Home")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=0)
        ttk.Label(tab, text="A LITTLE ORDER FOR YOUR DIGITAL LIFE", style="Eyebrow.TLabel").grid(row=0, column=0, sticky="w", pady=(3, 10))
        ttk.Label(tab, text="Less clutter. More room.", style="Title.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(tab, text="Compress a project, protect something private, or find a file you put away.\nEverything here runs on your computer.",
                  style="Subtitle.TLabel", wraplength=690).grid(row=2, column=0, sticky="w", pady=(10, 22))
        cards = ttk.Frame(tab)
        cards.grid(row=3, column=0, sticky="ew")
        cards.columnconfigure((0, 1), weight=1, uniform="cards")
        self.home_buttons = {}
        definitions = (
            ("01 / COMPRESS", "Pack a folder", "Turn a project or folder into one .gmw archive. Choose speed, size or a searchable Vault.", "Choose folder…", self._home_compress),
            ("02 / PROTECT", "Keep a file private", "Create an encrypted Sealed File with a password and a separate recovery key.", "Choose file…", self._home_protect),
            ("03 / RESTORE", "Get your files back", "Open a .gmw archive or .rtsf Sealed File, then choose where to restore a copy.", "Open to restore…", self._home_restore),
            ("04 / FIND", "Search what you stored", "Find filenames and indexed text in a queryable Vault. Browse its data tables when you need more.", "Search a Vault", lambda: self._go_to("Search Vault")),
        )
        home_cards = []
        for index, (eyebrow, title, description, action, command) in enumerate(definitions):
            card = ttk.Frame(cards, padding=18, relief="solid", borderwidth=1)
            home_cards.append(card)
            card.grid(row=index // 2, column=index % 2, sticky="nsew",
                      padx=(0, 12) if index % 2 == 0 else (0, 0), pady=(0, 12))
            card.columnconfigure(0, weight=1)
            card.rowconfigure(2, weight=1)
            ttk.Label(card, text=eyebrow, style="Eyebrow.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=title, font=("Segoe UI", 14, "bold")).grid(row=1, column=0, sticky="w", pady=(10, 8))
            ttk.Label(card, text=description, style="Subtitle.TLabel", wraplength=295).grid(row=2, column=0, sticky="nw")
            button = ttk.Button(card, text=action, command=command,
                                style="Action.TButton" if index == 0 else "TButton")
            button.grid(row=3, column=0, sticky="w", pady=(18, 0))
            self.home_buttons[title] = button
            self.action_buttons.append(button)
        def arrange_cards(event) -> None:
            columns = 2 if event.width >= int(770 * self.scale) else 1
            cards.columnconfigure(0, weight=1, uniform="cards" if columns == 2 else "")
            cards.columnconfigure(1, weight=1 if columns == 2 else 0,
                                  uniform="cards" if columns == 2 else "", minsize=0)
            for index, card in enumerate(home_cards):
                card.grid_configure(row=index // columns, column=index % columns,
                                    padx=(0, 12) if columns == 2 and index % 2 == 0 else (0, 0))
        self.page_scrollers["Home"].canvas.bind("<Configure>", arrange_cards, add="+")
        ttk.Label(tab, text="Compression is not encryption. Use Protect files or enable encryption when creating an archive.",
                  style="Subtitle.TLabel", wraplength=750).grid(row=4, column=0, sticky="w", pady=(10, 4))
        ttk.Label(tab, text="Preview build · Test with copies of your files · Ctrl+O to open · Ctrl+1 for Home",
                  style="Subtitle.TLabel", wraplength=750).grid(row=5, column=0, sticky="w", pady=(3, 0))

    def _path_row(self, parent, row, label, variable, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=10, padx=(0, 14))
        entry = ttk.Entry(parent, textvariable=variable, width=26)
        entry.grid(row=row, column=1, sticky="ew", pady=10)
        self.path_entries[str(variable)] = entry
        def choose() -> None:
            if not self.busy:
                command()
        button = ttk.Button(parent, text="Browse…", command=choose)
        button.grid(row=row, column=2, sticky="e", pady=10, padx=(10, 0))
        self.action_buttons.append(button)

    def _choose_source(self) -> None:
        if self.busy:
            return
        selected = filedialog.askdirectory(parent=self.root, title="Choose the folder to compress", mustexist=True)
        if not selected:
            return
        destination = updated_archive_destination(
            self.source_folder.get(), selected, self.create_archive.get(),
            windows_app.PROFILE_OPTIONS[self.profile_label.get()],
        )
        self.source_folder.set(selected)
        self.create_archive.set(destination)
        self.path_entries[str(self.source_folder)].focus_set()

    def _home_compress(self) -> None:
        if self._go_to("Create archive"):
            self._choose_source()

    def _home_protect(self) -> None:
        if self._go_to("Secure files"):
            self.secure_modes.select(self.secure_protect_mode)
            self._choose_seal_source()

    def _home_restore(self) -> None:
        self._open_existing(restore=True)

    def _open_existing(self, *, restore: bool = False) -> None:
        if self.busy:
            return
        selected = filedialog.askopenfilename(
            parent=self.root, title="Open a Rat-Trap archive or Sealed File",
            filetypes=[("Rat-Trap files", "*.gmw *.rtsf *.db"), ("All files", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        suffix = path.suffix.lower()
        if suffix == ".rtsf":
            self.apply_launch_request(windows_app.LaunchRequest("open-sealed", path))
        elif suffix == ".gmw":
            if restore:
                self._go_to("Extract archive")
                self.extract_archive.set(str(path))
                if not self.extract_folder.get().strip():
                    self.extract_folder.set(str(path.parent / f"{path.stem}_extracted"))
                self.status_text.set("Archive selected — choose Extract when ready")
            else:
                self.apply_launch_request(windows_app.LaunchRequest("open-archive", path))
        elif suffix == ".db":
            self._go_to("Search Vault")
            self.vault_archive.set(str(path))
            self.data_archive.set(str(path))
            self.status_text.set("Database selected — Search checks whether it is a Rat-Trap Vault")
        else:
            messagebox.showwarning("Rat-Trap", "Choose a .gmw archive, .rtsf Sealed File or .db Vault. Recovery keys are not archives.", parent=self.root)

    def apply_launch_request(self, request: windows_app.LaunchRequest) -> None:
        if not self.busy:
            super().apply_launch_request(request)

    def _scroll_page(self, event) -> None:
        # Let nested editors and result lists keep their own scrolling behaviour.
        if isinstance(event.widget, (tk.Text, tk.Listbox, ttk.Treeview, ttk.Combobox)):
            return
        widget = event.widget
        while widget is not None and widget != self._sidebar_canvas:
            widget = getattr(widget, "master", None)
        if widget == self._sidebar_canvas:
            if event.delta:
                self._sidebar_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return
        current = self.tabs.select()
        if not current:
            return
        for page in self.page_scrollers.values():
            widget = event.widget
            while widget is not None and widget != page:
                widget = getattr(widget, "master", None)
            if widget == page and str(page.content) == current:
                if event.delta:
                    page.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return

    def _style_text_widgets(self, widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            if isinstance(child, tk.Text):
                child.configure(background="#F7FAFA", foreground=COLORS["ink"],
                                insertbackground=COLORS["ink"], selectbackground=COLORS["accent"],
                                selectforeground="white", relief="flat", padx=10, pady=8)
            self._style_text_widgets(child)

    def _build_about_tab(self) -> None:
        super()._build_about_tab()
        for heading in self.about_tab.grid_slaves(row=0, column=0):
            heading.configure(text=f"Rat-Trap — {PREVIEW_LABEL}")

    def _copy_support_details(self) -> None:
        super()._copy_support_details()
        self.root.clipboard_append(f"\nInterface: {PREVIEW_LABEL} (5.7.0-desktop-preview.1)")


def _ui_self_test() -> None:
    """Exercise the actual preview UI in a frozen build without showing a window."""
    with tempfile.TemporaryDirectory(prefix="rat-trap-preview-ui-test-") as temporary:
        log = diagnostics.LocalDiagnostics(Path(temporary))
        root = tk.Tk()
        root.withdraw()
        try:
            app = DesktopPreviewApp(root, diagnostic_log=log)
            root.update_idletasks()
            if set(app.pages) != set(WORKSPACE_NAMES):
                raise RuntimeError("Preview workspace inventory mismatch")
            if app.tabs.select() != str(app.pages["Home"]):
                raise RuntimeError("Preview did not start on Home")
            for title in WORKSPACE_NAMES:
                if not app._go_to(title) or app.tabs.select() != str(app.pages[title]):
                    raise RuntimeError("Preview navigation failed")
            app.apply_launch_request(windows_app.LaunchRequest("open-sealed", Path("sample.rtsf")))
            if app.tabs.select() != str(app.secure_files_tab) or app.busy:
                raise RuntimeError("Preview activation did not remain a preselection")
            app.busy = True
            if app._go_to("Home"):
                raise RuntimeError("Busy preview permitted navigation")
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
    diagnostic_log = diagnostics.LocalDiagnostics()
    root = None
    try:
        request = windows_app._parse_launch_request(sys.argv[1:])
        root = tk.Tk()
        app = DesktopPreviewApp(root, diagnostic_log=diagnostic_log)
        if request is not None:
            app.apply_launch_request(request)
        root.mainloop()
    except Exception as exc:
        reference = diagnostic_log.record_exception(
            "app.startup.failed", exc,
            details={"component": "windows_ui", "stage": "startup", "status": "failed"},
        )
        if root is None:
            root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Rat-Trap", f"The desktop preview could not start.\n\nError reference: {reference}", parent=root)
        root.destroy()
    finally:
        diagnostic_log.close()


if __name__ == "__main__":
    main()
