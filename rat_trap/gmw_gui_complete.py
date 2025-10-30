"""GMW Tool GUI - Complete graphical interface for all GMW archive operations."""

import json
import os
import sqlite3
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# Import the GMW tool functions
import gmw_tool


class GMWCompleteGui:
    def __init__(self, root):
        self.root = root
        self.root.title("GMW Archive Tool - Complete")
        self.root.geometry("700x500")
        self.root.resizable(True, True)
        
        # Variables for each operation
        self.operation = tk.StringVar(value="")
        self.archive_path = tk.StringVar()
        self.folder_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.server_host = tk.StringVar(value="127.0.0.1")
        self.server_port = tk.IntVar(value=8000)
        
        # Compression options
        self.chunk_size = tk.IntVar(value=512 * 1024)
        self.use_zstd = tk.BooleanVar(value=True)
        self.zstd_level = tk.IntVar(value=3)
        self.use_checksum = tk.BooleanVar(value=True)
        
        # Create main interface
        self.create_main_menu()
    
    def create_main_menu(self):
        """Create the main menu for selecting operations."""
        # Clear the root window
        for widget in self.root.winfo_children():
            widget.destroy()
        
        self.root.title("GMW Archive Tool - Main Menu")
        
        main_frame = tk.Frame(self.root, padx=40, pady=40)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(
            main_frame,
            text="GMW Archive Tool",
            font=("Arial", 20, "bold")
        ).pack(pady=(0, 10))
        
        tk.Label(
            main_frame,
            text="Select an operation:",
            font=("Arial", 12)
        ).pack(pady=(0, 30))
        
        # Create buttons for each operation
        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(expand=True)
        
        operations = [
            ("📦 Compress", "Create a new GMW archive from a folder", self.show_compress_ui, "#4CAF50"),
            ("📂 Extract", "Extract files from a GMW archive", self.show_extract_ui, "#2196F3"),
            ("🔍 Search", "Search and browse archive contents", self.show_search_ui, "#00BCD4"),
            ("ℹ️ Info", "View information about a GMW archive", self.show_info_ui, "#FF9800"),
            ("🌐 Serve", "Serve a GMW archive over HTTP", self.show_serve_ui, "#9C27B0"),
        ]
        
        for i, (title, desc, command, color) in enumerate(operations):
            btn = tk.Button(
                btn_frame,
                text=title,
                font=("Arial", 14, "bold"),
                width=20,
                height=2,
                bg=color,
                fg="white",
                command=command,
                cursor="hand2"
            )
            btn.pack(pady=10)
            
            tk.Label(
                btn_frame,
                text=desc,
                font=("Arial", 9),
                fg="gray"
            ).pack(pady=(0, 15))
    
    def show_compress_ui(self):
        """Show the compress operation UI."""
        self.clear_window()
        self.root.title("GMW Archive Tool - Compress")
        
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        tk.Label(
            frame,
            text="Create Archive",
            font=("Arial", 16, "bold")
        ).pack(pady=(0, 20))
        
        # Source folder
        tk.Label(frame, text="Source Folder:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        folder_frame = tk.Frame(frame)
        folder_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Entry(folder_frame, textvariable=self.folder_path, state="readonly", width=60).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(folder_frame, text="Browse...", command=self.browse_compress_folder, width=12).pack(side=tk.LEFT)
        
        # Output file
        tk.Label(frame, text="Output Archive:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        output_frame = tk.Frame(frame)
        output_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Entry(output_frame, textvariable=self.output_path, state="readonly", width=60).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(output_frame, text="Browse...", command=self.browse_compress_output, width=12).pack(side=tk.LEFT)
        
        # Options
        options_frame = tk.LabelFrame(frame, text="Compression Options", padx=10, pady=10)
        options_frame.pack(fill=tk.X, pady=(10, 15))
        
        tk.Checkbutton(options_frame, text="Use Zstandard compression", variable=self.use_zstd).pack(anchor=tk.W)
        tk.Checkbutton(options_frame, text="Generate SHA256 checksums", variable=self.use_checksum).pack(anchor=tk.W)
        
        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        tk.Button(btn_frame, text="← Back", command=self.create_main_menu, width=12).pack(side=tk.LEFT)
        tk.Button(
            btn_frame,
            text="Create Archive",
            command=self.execute_compress,
            width=15,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 10, "bold")
        ).pack(side=tk.RIGHT)
    
    def show_extract_ui(self):
        """Show the extract operation UI."""
        self.clear_window()
        self.root.title("GMW Archive Tool - Extract")
        
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        tk.Label(
            frame,
            text="Extract Archive",
            font=("Arial", 16, "bold")
        ).pack(pady=(0, 20))
        
        # Archive file
        tk.Label(frame, text="Archive File:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        archive_frame = tk.Frame(frame)
        archive_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Entry(archive_frame, textvariable=self.archive_path, state="readonly", width=60).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(archive_frame, text="Browse...", command=self.browse_archive, width=12).pack(side=tk.LEFT)
        
        # Output folder
        tk.Label(frame, text="Extract To:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        output_frame = tk.Frame(frame)
        output_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Entry(output_frame, textvariable=self.output_path, state="readonly", width=60).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(output_frame, text="Browse...", command=self.browse_extract_folder, width=12).pack(side=tk.LEFT)
        
        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        tk.Button(btn_frame, text="← Back", command=self.create_main_menu, width=12).pack(side=tk.LEFT)
        tk.Button(
            btn_frame,
            text="Extract Files",
            command=self.execute_extract,
            width=15,
            bg="#2196F3",
            fg="white",
            font=("Arial", 10, "bold")
        ).pack(side=tk.RIGHT)
    
    def show_search_ui(self):
        """Show the search operation UI."""
        self.clear_window()
        self.root.title("GMW Archive Tool - Search")
        
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        tk.Label(
            frame,
            text="Search Archive",
            font=("Arial", 16, "bold")
        ).pack(pady=(0, 20))
        
        # Archive file
        tk.Label(frame, text="Archive File:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        archive_frame = tk.Frame(frame)
        archive_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Entry(archive_frame, textvariable=self.archive_path, state="readonly", width=60).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(archive_frame, text="Browse...", command=self.browse_archive, width=12).pack(side=tk.LEFT)
        
        # Search controls
        search_frame = tk.Frame(frame)
        search_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Label(search_frame, text="Search:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        self.search_query = tk.Entry(search_frame, width=40)
        self.search_query.pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Button(search_frame, text="Search Files", command=self.execute_search, width=12, bg="#00BCD4", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(search_frame, text="List All", command=self.list_all_files, width=12, bg="#00BCD4", fg="white").pack(side=tk.LEFT)
        
        # Results display with scrollbar
        results_frame = tk.LabelFrame(frame, text="Search Results", padx=10, pady=10)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 15))
        
        # Create Treeview for file list
        tree_scroll = tk.Scrollbar(results_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.search_tree = ttk.Treeview(
            results_frame,
            columns=("path", "size", "chunks"),
            show="headings",
            yscrollcommand=tree_scroll.set,
            height=15
        )
        tree_scroll.config(command=self.search_tree.yview)
        
        self.search_tree.heading("path", text="File Path")
        self.search_tree.heading("size", text="Size")
        self.search_tree.heading("chunks", text="Chunks")
        
        self.search_tree.column("path", width=400)
        self.search_tree.column("size", width=100)
        self.search_tree.column("chunks", width=80)
        
        self.search_tree.pack(fill=tk.BOTH, expand=True)
        
        # File count label
        self.search_count_label = tk.Label(results_frame, text="No results", fg="gray")
        self.search_count_label.pack(pady=(5, 0))
        
        # Extract selected button
        extract_btn_frame = tk.Frame(frame)
        extract_btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(
            extract_btn_frame,
            text="Extract Selected",
            command=self.extract_selected_files,
            width=15,
            bg="#2196F3",
            fg="white"
        ).pack(side=tk.RIGHT, padx=5)
        
        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        tk.Button(btn_frame, text="← Back", command=self.create_main_menu, width=12).pack(side=tk.LEFT)
    
    def show_info_ui(self):
        """Show the info operation UI."""
        self.clear_window()
        self.root.title("GMW Archive Tool - Info")
        
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        tk.Label(
            frame,
            text="Archive Information",
            font=("Arial", 16, "bold")
        ).pack(pady=(0, 20))
        
        # Archive file
        tk.Label(frame, text="Archive File:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        archive_frame = tk.Frame(frame)
        archive_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Entry(archive_frame, textvariable=self.archive_path, state="readonly", width=60).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(archive_frame, text="Browse...", command=self.browse_archive, width=12).pack(side=tk.LEFT)
        
        # Info display
        info_frame = tk.LabelFrame(frame, text="Archive Details", padx=10, pady=10)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 15))
        
        self.info_text = scrolledtext.ScrolledText(info_frame, height=15, width=70, wrap=tk.WORD, state=tk.DISABLED)
        self.info_text.pack(fill=tk.BOTH, expand=True)
        
        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        tk.Button(btn_frame, text="← Back", command=self.create_main_menu, width=12).pack(side=tk.LEFT)
        tk.Button(
            btn_frame,
            text="View Info",
            command=self.execute_info,
            width=15,
            bg="#FF9800",
            fg="white",
            font=("Arial", 10, "bold")
        ).pack(side=tk.RIGHT)
    
    def show_serve_ui(self):
        """Show the serve operation UI."""
        self.clear_window()
        self.root.title("GMW Archive Tool - Serve")
        
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        tk.Label(
            frame,
            text="Serve Archive Over HTTP",
            font=("Arial", 16, "bold")
        ).pack(pady=(0, 20))
        
        # Archive file
        tk.Label(frame, text="Archive File:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        archive_frame = tk.Frame(frame)
        archive_frame.pack(fill=tk.X, pady=(5, 15))
        
        tk.Entry(archive_frame, textvariable=self.archive_path, state="readonly", width=60).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(archive_frame, text="Browse...", command=self.browse_archive, width=12).pack(side=tk.LEFT)
        
        # Server options
        server_frame = tk.LabelFrame(frame, text="Server Options", padx=10, pady=10)
        server_frame.pack(fill=tk.X, pady=(10, 15))
        
        host_frame = tk.Frame(server_frame)
        host_frame.pack(fill=tk.X, pady=5)
        tk.Label(host_frame, text="Host:", width=10, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(host_frame, textvariable=self.server_host, width=30).pack(side=tk.LEFT, padx=(0, 10))
        
        port_frame = tk.Frame(server_frame)
        port_frame.pack(fill=tk.X, pady=5)
        tk.Label(port_frame, text="Port:", width=10, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(port_frame, textvariable=self.server_port, width=30).pack(side=tk.LEFT, padx=(0, 10))
        
        # Server status
        self.server_status = tk.Label(frame, text="Server not running", fg="gray", font=("Arial", 10, "italic"))
        self.server_status.pack(pady=10)
        
        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        tk.Button(btn_frame, text="← Back", command=self.create_main_menu, width=12).pack(side=tk.LEFT)
        self.serve_button = tk.Button(
            btn_frame,
            text="Start Server",
            command=self.execute_serve,
            width=15,
            bg="#9C27B0",
            fg="white",
            font=("Arial", 10, "bold")
        )
        self.serve_button.pack(side=tk.RIGHT)
    
    def clear_window(self):
        """Clear all widgets from the window."""
        for widget in self.root.winfo_children():
            widget.destroy()
    
    def browse_compress_folder(self):
        """Browse for source folder to compress."""
        folder = filedialog.askdirectory(title="Select Folder to Archive")
        if folder:
            self.folder_path.set(folder)
            # Auto-suggest output filename
            if not self.output_path.get():
                folder_name = Path(folder).name
                self.output_path.set(str(Path.home() / f"{folder_name}_archive.gmw"))
    
    def browse_compress_output(self):
        """Browse for output archive file."""
        initial_name = "archive.gmw"
        if self.folder_path.get():
            folder_name = Path(self.folder_path.get()).name
            initial_name = f"{folder_name}_archive.gmw"
        
        file_path = filedialog.asksaveasfilename(
            title="Save Archive As",
            initialfile=initial_name,
            defaultextension=".gmw",
            filetypes=[("GMW Archive", "*.gmw"), ("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        if file_path:
            self.output_path.set(file_path)
    
    def browse_archive(self):
        """Browse for archive file."""
        file_path = filedialog.askopenfilename(
            title="Select GMW Archive",
            filetypes=[("GMW Archive", "*.gmw"), ("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        if file_path:
            self.archive_path.set(file_path)
    
    def browse_extract_folder(self):
        """Browse for extraction destination folder."""
        folder = filedialog.askdirectory(title="Select Destination Folder")
        if folder:
            self.output_path.set(folder)
    
    def execute_compress(self):
        """Execute the compress operation."""
        if not self.folder_path.get():
            messagebox.showwarning("Missing Input", "Please select a source folder.")
            return
        
        if not self.output_path.get():
            messagebox.showwarning("Missing Output", "Please select an output location.")
            return
        
        self.show_progress_window("Creating Archive", self.compress_worker)
    
    def execute_extract(self):
        """Execute the extract operation."""
        if not self.archive_path.get():
            messagebox.showwarning("Missing Input", "Please select an archive file.")
            return
        
        if not self.output_path.get():
            messagebox.showwarning("Missing Output", "Please select a destination folder.")
            return
        
        self.show_progress_window("Extracting Files", self.extract_worker)
    
    def execute_search(self):
        """Execute file search in the archive."""
        if not self.archive_path.get():
            messagebox.showwarning("Missing Input", "Please select an archive file.")
            return
        
        query = self.search_query.get().strip()
        if not query:
            messagebox.showwarning("Missing Query", "Please enter a search term.")
            return
        
        try:
            archive = Path(self.archive_path.get())
            conn = sqlite3.connect(archive)
            cursor = conn.cursor()
            
            # Search for files matching the query (case-insensitive)
            cursor.execute(
                "SELECT path, size, chunk_ids FROM files WHERE path LIKE ? ORDER BY path",
                (f"%{query}%",)
            )
            
            results = cursor.fetchall()
            conn.close()
            
            # Clear previous results
            for item in self.search_tree.get_children():
                self.search_tree.delete(item)
            
            # Display results
            for path, size, chunk_ids in results:
                chunk_count = len(json.loads(chunk_ids))
                size_str = self.format_size(size)
                self.search_tree.insert("", tk.END, values=(path, size_str, chunk_count))
            
            self.search_count_label.config(
                text=f"Found {len(results)} file(s) matching '{query}'",
                fg="green" if results else "gray"
            )
            
        except Exception as e:
            messagebox.showerror("Search Error", f"Failed to search archive:\n{str(e)}")
    
    def list_all_files(self):
        """List all files in the archive."""
        if not self.archive_path.get():
            messagebox.showwarning("Missing Input", "Please select an archive file.")
            return
        
        try:
            archive = Path(self.archive_path.get())
            conn = sqlite3.connect(archive)
            cursor = conn.cursor()
            
            # Get all files
            cursor.execute("SELECT path, size, chunk_ids FROM files ORDER BY path")
            results = cursor.fetchall()
            conn.close()
            
            # Clear previous results
            for item in self.search_tree.get_children():
                self.search_tree.delete(item)
            
            # Display results
            for path, size, chunk_ids in results:
                chunk_count = len(json.loads(chunk_ids))
                size_str = self.format_size(size)
                self.search_tree.insert("", tk.END, values=(path, size_str, chunk_count))
            
            self.search_count_label.config(
                text=f"Total: {len(results)} file(s) in archive",
                fg="green" if results else "gray"
            )
            
        except Exception as e:
            messagebox.showerror("List Error", f"Failed to list files:\n{str(e)}")
    
    def extract_selected_files(self):
        """Extract selected files from the archive."""
        selection = self.search_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select one or more files to extract.")
            return
        
        if not self.archive_path.get():
            messagebox.showwarning("Missing Input", "No archive selected.")
            return
        
        # Ask for output directory
        output_dir = filedialog.askdirectory(title="Select Destination Folder")
        if not output_dir:
            return
        
        try:
            archive = Path(self.archive_path.get())
            output_path = Path(output_dir)
            
            # Get selected file paths
            selected_files = []
            for item in selection:
                values = self.search_tree.item(item)['values']
                selected_files.append(values[0])  # Path is first column
            
            # Extract selected files
            conn = sqlite3.connect(archive)
            cursor = conn.cursor()
            
            extracted_count = 0
            for file_path in selected_files:
                cursor.execute(
                    "SELECT size, chunk_ids, chunk_sizes FROM files WHERE path = ?",
                    (file_path,)
                )
                result = cursor.fetchone()
                
                if result:
                    size, chunk_ids_json, chunk_sizes_json = result
                    chunk_ids = json.loads(chunk_ids_json)
                    chunk_sizes = json.loads(chunk_sizes_json)
                    
                    # Create output file path
                    out_file = output_path / file_path
                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Extract chunks and write file
                    with open(out_file, 'wb') as f:
                        for chunk_id in chunk_ids:
                            cursor.execute("SELECT data, compressor FROM chunks WHERE id = ?", (chunk_id,))
                            chunk_result = cursor.fetchone()
                            if chunk_result:
                                compressed_data, compressor = chunk_result
                                
                                # Decompress chunk
                                if compressor == "zstd":
                                    import zstandard as zstd
                                    dctx = zstd.ZstdDecompressor()
                                    data = dctx.decompress(compressed_data)
                                elif compressor == "zlib":
                                    import zlib
                                    data = zlib.decompress(compressed_data)
                                else:
                                    data = compressed_data
                                
                                f.write(data)
                    
                    extracted_count += 1
            
            conn.close()
            
            messagebox.showinfo(
                "Extraction Complete",
                f"Successfully extracted {extracted_count} file(s) to:\n{output_path}"
            )
            
        except Exception as e:
            messagebox.showerror("Extraction Error", f"Failed to extract files:\n{str(e)}")
    
    def format_size(self, size_bytes):
        """Format size in bytes to human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
    
    def execute_info(self):
        """Execute the info operation."""
        if not self.archive_path.get():
            messagebox.showwarning("Missing Input", "Please select an archive file.")
            return
        
        try:
            archive = Path(self.archive_path.get())
            meta = gmw_tool.read_metadata(archive)
            
            # Display info
            self.info_text.config(state=tk.NORMAL)
            self.info_text.delete(1.0, tk.END)
            
            info = f"Archive: {archive.name}\n"
            info += f"Path: {archive}\n"
            info += f"\n{'='*60}\n\n"
            info += f"Format: {meta.format}\n"
            info += f"Files: {meta.file_count:,}\n"
            info += f"Total Size: {meta.total_bytes / (1024*1024):.2f} MB\n"
            info += f"Compressor: {meta.compressor}\n"
            info += f"Chunk Size: {meta.chunk_size / 1024:.0f} KB\n"
            info += f"Checksum Algorithm: {meta.checksum_algorithm}\n"
            
            if meta.checksum:
                info += f"Checksum: {meta.checksum}\n"
            
            import datetime
            created = datetime.datetime.fromtimestamp(meta.created_at)
            info += f"Created: {created.strftime('%Y-%m-%d %H:%M:%S')}\n"
            info += f"Build Time: {meta.elapsed_seconds:.2f} seconds\n"
            
            # Get archive file size
            archive_size = archive.stat().st_size
            info += f"\nArchive Size: {archive_size / (1024*1024):.2f} MB\n"
            
            if meta.total_bytes > 0:
                ratio = (1 - archive_size / meta.total_bytes) * 100
                info += f"Space Saved: {ratio:.1f}%\n"
            
            self.info_text.insert(1.0, info)
            self.info_text.config(state=tk.DISABLED)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read archive info:\n{str(e)}")
    
    def execute_serve(self):
        """Execute the serve operation."""
        if not self.archive_path.get():
            messagebox.showwarning("Missing Input", "Please select an archive file.")
            return
        
        messagebox.showinfo(
            "Server Feature",
            "The HTTP server feature requires running in a terminal.\n\n"
            f"To serve this archive, run:\n\n"
            f'python gmw_tool.py serve "{self.archive_path.get()}" --host {self.server_host.get()} --port {self.server_port.get()}\n\n'
            "The server will start and display the URL to access it."
        )
    
    def show_progress_window(self, title, worker_func):
        """Show a progress window and run worker function."""
        self.clear_window()
        self.root.title(f"GMW Archive Tool - {title}")
        
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(frame, text=title, font=("Arial", 16, "bold")).pack(pady=(0, 20))
        
        self.progress_status = tk.Label(frame, text="Initializing...", wraplength=600)
        self.progress_status.pack(pady=(0, 20))
        
        self.progress_bar = ttk.Progressbar(frame, mode='indeterminate', length=500)
        self.progress_bar.pack(pady=10)
        self.progress_bar.start(10)
        
        self.progress_text = scrolledtext.ScrolledText(frame, height=15, width=80, state=tk.DISABLED, wrap=tk.WORD)
        self.progress_text.pack(pady=10, fill=tk.BOTH, expand=True)
        
        self.progress_done_button = tk.Button(
            frame,
            text="Done",
            command=self.create_main_menu,
            width=12,
            state=tk.DISABLED,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 10, "bold")
        )
        self.progress_done_button.pack(side=tk.BOTTOM, pady=(10, 0))
        
        # Start worker thread
        thread = threading.Thread(target=worker_func, daemon=True)
        thread.start()
    
    def log_progress(self, message):
        """Log a message to the progress window."""
        def update():
            self.progress_text.config(state=tk.NORMAL)
            self.progress_text.insert(tk.END, message)
            self.progress_text.see(tk.END)
            self.progress_text.config(state=tk.DISABLED)
        
        self.root.after(0, update)
    
    def operation_complete(self, success, message):
        """Called when an operation is complete."""
        def update():
            self.progress_bar.stop()
            
            if success:
                self.progress_status.config(text=f"✓ {message}", fg="green")
                self.progress_bar.config(mode='determinate', value=100)
            else:
                self.progress_status.config(text=f"✗ {message}", fg="red")
            
            self.progress_done_button.config(state=tk.NORMAL)
        
        self.root.after(0, update)
    
    def compress_worker(self):
        """Worker thread for compression."""
        try:
            self.log_progress("Starting compression...\n\n")
            
            source_path = Path(self.folder_path.get())
            output_path = Path(self.output_path.get())
            
            self.log_progress(f"Source: {source_path}\n")
            self.log_progress(f"Output: {output_path}\n\n")
            
            compressor = "zstd" if self.use_zstd.get() else "zlib"
            checksum = "sha256" if self.use_checksum.get() else "none"
            
            result = gmw_tool.compress_folder(
                source_path,
                output_path,
                chunk_size=self.chunk_size.get(),
                compressor=compressor,
                zstd_level=self.zstd_level.get(),
                checksum_algorithm=checksum
            )
            
            self.log_progress("\n" + "="*60 + "\n")
            self.log_progress("✓ Compression completed successfully!\n")
            self.log_progress("="*60 + "\n\n")
            self.log_progress(f"Files processed: {result.file_count:,}\n")
            self.log_progress(f"Total size: {result.total_bytes / (1024*1024):.2f} MB\n")
            self.log_progress(f"Compression: {result.compressor}\n")
            self.log_progress(f"Chunk size: {result.chunk_size / 1024:.0f} KB\n")
            self.log_progress(f"Time elapsed: {result.elapsed_seconds:.2f} seconds\n\n")
            
            archive_size = output_path.stat().st_size
            self.log_progress(f"Archive size: {archive_size / (1024*1024):.2f} MB\n")
            
            if result.total_bytes > 0:
                ratio = (1 - archive_size / result.total_bytes) * 100
                self.log_progress(f"Space saved: {ratio:.1f}%\n")
            
            self.log_progress(f"\nArchive saved to:\n{output_path}\n")
            
            self.operation_complete(True, "Archive created successfully!")
            
        except Exception as e:
            error_msg = f"Error during compression: {str(e)}"
            self.log_progress(f"\n✗ {error_msg}\n")
            self.operation_complete(False, "Compression failed")
    
    def extract_worker(self):
        """Worker thread for extraction."""
        try:
            self.log_progress("Starting extraction...\n\n")
            
            archive_path = Path(self.archive_path.get())
            output_path = Path(self.output_path.get())
            
            self.log_progress(f"Archive: {archive_path}\n")
            self.log_progress(f"Destination: {output_path}\n\n")
            
            gmw_tool.extract_archive(archive_path, output_path)
            
            self.log_progress("\n" + "="*60 + "\n")
            self.log_progress("✓ Extraction completed successfully!\n")
            self.log_progress("="*60 + "\n\n")
            self.log_progress(f"Files extracted to:\n{output_path}\n")
            
            self.operation_complete(True, "Files extracted successfully!")
            
        except Exception as e:
            error_msg = f"Error during extraction: {str(e)}"
            self.log_progress(f"\n✗ {error_msg}\n")
            self.operation_complete(False, "Extraction failed")


def main():
    """Main entry point for the GUI."""
    root = tk.Tk()
    app = GMWCompleteGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
