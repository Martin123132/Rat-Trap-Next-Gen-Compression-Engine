# GMW Archive Tool - GUI Versions

This folder contains two GUI versions for the GMW archive tool:

## 1. Simple GUI (`gmw_gui.py`)
- **Focus**: Compress operation only
- **Features**: Step-by-step wizard for creating archives
- **Best for**: Quick archive creation with guided interface
- **Launch**: Double-click `run_gui.bat` or run `python gmw_gui.py`

## 2. Complete GUI (`gmw_gui_complete.py`) ⭐ RECOMMENDED
- **Focus**: All GMW operations in one interface
- **Features**:
  - **📦 Compress**: Create archives from folders
  - **📂 Extract**: Extract files from archives
  - **🔍 Search**: Search and browse archive contents, extract specific files
  - **ℹ️ Info**: View archive metadata and statistics
  - **🌐 Serve**: Instructions for serving archives over HTTP
- **Best for**: Full archive management
- **Launch**: Double-click `run_complete_gui.bat` or run `python gmw_gui_complete.py`## Quick Start

### Creating an Archive
1. Run `run_complete_gui.bat`
2. Click "📦 Compress"
3. Browse and select your source folder (e.g., `C:\Users\Glyn\Documents\stock`)
4. Browse and choose where to save the `.gmw` archive
5. Click "Create Archive"
6. Wait for completion and view statistics

### Extracting an Archive
1. Run `run_complete_gui.bat`
2. Click "📂 Extract"
3. Browse and select your `.gmw` archive file
4. Browse and choose destination folder
5. Click "Extract Files"

### Searching Archive Contents
1. Run `run_complete_gui.bat`
2. Click "🔍 Search"
3. Browse and select your `.gmw` archive file
4. **Option A - Search for specific files**:
   - Enter search term (e.g., "trading", ".py", "README")
   - Click "Search Files"
   - View matching files with size and chunk count
5. **Option B - List all files**:
   - Click "List All" to see complete file listing
6. **Extract specific files**:
   - Select one or more files from the results
   - Click "Extract Selected"
   - Choose destination folder

### Viewing Archive Info
1. Run `run_complete_gui.bat`
2. Click "ℹ️ Info"
3. Browse and select your `.gmw` archive file
4. Click "View Info"
5. See detailed metadata, file count, compression ratio, etc.

## File Extensions

- **`.gmw`**: GMW Archive format (recommended)
- **`.db`**: Also supported (it's SQLite underneath)

## Command-Line Tool

For advanced usage, you can still use the command-line tool:

```powershell
# Compress
python gmw_tool.py compress <folder> <output.gmw>

# Extract
python gmw_tool.py extract <archive.gmw> <destination>

# Info
python gmw_tool.py info <archive.gmw>

# Serve over HTTP
python gmw_tool.py serve <archive.gmw> --host 127.0.0.1 --port 8000
```

## Requirements

- Python 3.7+
- tkinter (usually included with Python)
- zstandard (optional, for better compression)

## Notes

- Archives are SQLite databases containing compressed file chunks
- Deduplication happens automatically at the chunk level
- Perfect for archiving code repositories, documents, etc.
