# Rat-Trap 5.2 — compressed backups, portable archives and queryable vaults

Rat-Trap gives Windows users one place to back up changing folders, recover an
older version, create a compact file for sharing, or turn stored data into a
searchable local vault.

## What Rat-Trap gives you

- **Compressed backup history.** Save many versioned folder captures in one
  repository and restore any generation as a complete verified folder.
- **Less repeated storage.** Content-defined chunking finds unchanged and
  shifted data across snapshots, while exact duplicate files are stored once.
- **Safe interrupted-run recovery.** Snapshot work is committed per file and
  resumes after a restart. A snapshot only enters history after its data and
  checksum-named manifest are complete.
- **Find a file across time.** Search stored paths, filenames and snapshot
  labels, then jump to the matching generation.
- **Portable `.gmw` archives.** Export any verified snapshot, or create a Fast,
  Balanced or Smallest archive directly.
- **Queryable Vaults.** Search filenames and supported text without unpacking;
  import CSV, TSV, JSON, JSONL, NDJSON and UCI data into local relational
  tables with point-and-click filters, read-only SQL and result export.
- **Visible integrity controls.** Quick checks validate structure and
  references. Full checks read every object and reconstruct every file hash.
- **Deliberate cleanup.** Preview retention first, protect important snapshots
  with pins, and apply only the exact reviewed plan. Version 5.2 moves removed
  data to recoverable trash rather than claiming it has already freed disk
  space.

For Windows, extract the release ZIP and double-click `Rat-Trap.exe`; Python is
not required. Open **Backups & history**, initialize a new empty repository,
choose a folder and select **Back up now**.

The command line exposes the same repository workflow:

```text
rat-trap repo-init <repository>
rat-trap repo-issues <repository>
rat-trap repo-jobs <repository>
rat-trap repo-snapshot <repository> <folder> --label "Before edit"
rat-trap repo-list <repository>
rat-trap repo-search <repository> <filename>
rat-trap repo-restore <repository> <snapshot-id> <new-folder>
rat-trap repo-verify <repository>
rat-trap repo-prune <repository>
```

If an interrupted source is later disconnected or moved, `repo-jobs` exposes
the exact pending job and `repo-abandon-job` can move only that confirmed job
to recoverable trash; the Windows app provides the same **Interrupted jobs**
action.

Rat-Trap 5.2 keeps the supported 4.2–5.1 `.gmw` families readable and does not
change their formats.

## Technical evidence and buyer diligence

The public product summary above describes Rat-Trap’s own capabilities. The
technical lane keeps the detailed evidence, formats, test boundaries and
limitations available for engineering review:

- [5.2 repository format and safety model](docs/REPOSITORY-FORMAT.md)
- [5.2 repository release gate](docs/REPOSITORY-GATE-5.2.0.md)
- [Benchmark audit](BENCHMARK-AUDIT.md)
- [Queryable Vault format and workflow](VAULT-README.md)
- [5.1.0 preserved baseline](docs/BASELINE-5.1.0.md)
- [5.1.1 compatibility gate](docs/COMPATIBILITY-GATE.md)
- [GMW format registry](docs/GMW-FORMAT-REGISTRY.md)
- [Benchmark history and evidence status](docs/BENCHMARK-HISTORY.md)
- [Product and evidence lanes](docs/PRODUCT-EVIDENCE-LANES.md)

Current repository snapshots are local and checksum-verified, not encrypted.
Authenticated encryption, recovery keys, VSS handling for open files,
scheduling, off-site storage and permanent trash expiry are later stages, not
hidden 5.2 claims. Version 5.2 reads a live folder file by file and atomically
publishes the completed capture; without VSS it does not claim a filesystem-wide
point-in-time view while applications are actively changing multiple files.
It refuses EFS-encrypted, NTFS-compressed, sparse, hard-linked, reparse-point
and alternate-data-stream inputs instead of silently changing their meaning.

---

<img width="1491" height="1055" alt="ec579140-507e-451a-9b3e-9cb2ca2f2a1b" src="https://github.com/user-attachments/assets/b701016e-35a7-4612-aaa6-fbdc017b581a" />

## Historical project narrative

The material below records the project's original positioning and 2025
campaign. Treat its benchmark numbers as historical scoped results, not a
current cross-market certification; the complete status and limitations are
linked above.

# 🪤 Rat-Trap — Next-Gen Compression Engine  

**"Time is money. Space is motion. Rat-Trap is both."**

Rat-Trap is a **high-performance, GMW-powered data compression system** built by Glyn Evans and Martin ollett, inspired by the **Motion-TimeSpace (MTS) physics framework**. It’s engineered to **trap chaotic data**—text, images, audio, structured records—and reorganize it into the smallest, fastest, most efficient form possible.

Where conventional compression tools trade speed for size, **Rat-Trap targets a stronger speed-to-ratio balance.** In one recorded 2025 image test, GMW Zstd-1 created its folder archive **93.68 times faster than tar.xz**. That is a historical workload-specific result, not a promise for every folder.

## 🚀 Why Rat-Trap? (The New Standard)

In the recorded 2025 image and audio tests, GMW delivered the fastest
folder-archive creation times among the archive methods in the matrix. It is
built for workloads where waiting on older archive pipelines is costly.

<img width="1491" height="1055" alt="853953d8-95b3-40db-b605-93b22c090166" src="https://github.com/user-attachments/assets/6af4be24-94a8-473b-828f-97ded7eecc80" />


| Metric | GMW (ZSTD-3) | Tar/Gzip (Legacy Standard) | Tar/XZ (Slowest/Best Ratio) | Pure ZSTD (Modern Baseline) |
| :--- | :--- | :--- | :--- | :--- |
| **Image Compression Time** | **$\mathbf{2.54s}$** | $11.46s$ | $122.95s$ | $3.31s$ |
| **Speedup (vs. Gzip)** | **$4.5\times$ faster** | $1.0\times$ | $0.09\times$ | $3.5\times$ faster |
| **Audio Compression Time** | **$\mathbf{8.82s}$** | $36.04s$ | $236.70s$ | $1253.34s$ |
| **Speedup (vs. Tar/XZ)** | **$26.8\times$ faster** | $6.6\times$ faster | $1.0\times$ | $0.19\times$ faster |

  * **🥇 Historical Image Win:** GMW-ZSTD-1 was the **fastest folder archive tested** for the recorded image dataset.
  * **⏱ Up to $\mathbf{93.68\times}$ faster** than `tar.xz` in that 2025 image cell.
  * **⚖️ Strong Recorded Range:** The fastest GMW profile was **$3.20\times$ to $8.73\times$ faster than `tar.gz`** across the four recorded historical folder datasets; archive size remained workload-dependent.
  * **🧠 Physics-Inspired Design** based on Motion-TimeSpace curvature dynamics.
  * **🌐 Fully self-contained Python script**—no external build system required.

-----

## 🧠 How It Works

<img width="1491" height="1055" alt="7b79e0fb-9f84-4cba-9972-ea564432f778" src="https://github.com/user-attachments/assets/f5b015f7-abb8-41f5-9a3c-7c5575cabc3d" />

Rat-Trap’s core compression engine is built around **GMW (Geometric Motion Wrapper)**—a custom archival format derived from MBT2 physics simulations. It optimizes for file aggregation and parallel processing, solving the I/O bottlenecks that choke traditional compression tools.

Key Innovations:

  * **Motion-TimeSpace Compression** – Organizes data based on motion-derived entropy gradients, mimicking how tension diffuses in physical systems.
  * **Parallelized Bucket Packing** – Optimized thread-based bucket construction for multi-core compression, which is the source of its massive speed advantage over single-stream `tar` pipes.
  * **Z-Order Encoding** – Efficient voxel key mapping using Morton encoding for enhanced spatial data compaction.
  * **Adaptive ZSTD Layers** – Configurable trade-offs between speed and compression depth (levels 1–9) to match specific latency requirements.
  * **Planned Authenticated Encryption** – Not included in Rat-Trap 5.2; the current `.gmw` and repository formats are not encrypted.

-----

## 🛠 Installation

Rat-Trap is now published as a standard Python package. Install it into your
environment (and pull in the optional extras if you want the original
cryptography/xxhash helpers):

```bash
pip install .
# or build a wheel: python -m build

# optional extras
pip install .[crypto]
```

The `crypto` extra retains dependencies used by historical helper code. It
does not encrypt Rat-Trap 5.2 archives or repositories.

> **Note:** The default compression engine uses [Zstandard]. The package declares
> it as a dependency, but if you install manually without dependencies the CLI
> will automatically fall back to zlib and warn you.

-----

## ⚙️ Usage

Run Rat-Trap directly:

```bash
rat-trap --help
 ```

 The CLI exposes sub-commands instead of interactive prompts:

1.  `rat-trap compress <folder> <archive>` – ingest a folder into a `.gmw` archive.
2.  `rat-trap extract <archive> <destination>` – extract an archive back to disk.
3.  `rat-trap info <archive>` – show stored metadata without extracting.
4.  `rat-trap export-zip <archive.gmw> <output.zip>` – export a `.gmw` archive to a standard ZIP for Windows/WinZip compatibility.
5.  `rat-trap serve <archive>` – expose the archive via HTTP chunk streaming.

[Zstandard]: https://facebook.github.io/zstd/

### 📦 Compress a folder

```bash
python gmw_tool.py
# ... prompts you for action ...
# Choose an action (1/2): 1
Enter the path of the folder to compress: ./dataset
Enter the output .gmw file name: data_archive.gmw
```

### 📂 Extract a `.gmw` archive

```bash
python gmw_tool.py
# ... prompts you for action ...
# Choose an action (1/2): 2
Enter the path of the .gmw file to extract: data_archive.gmw
Enter the output folder: ./restored
```

## 🔁 New Experimental Toolchain

To explore new data-transfer frontiers we now ship three experimental
spin-offs of the original `gmw_tool.py`. Each script keeps the familiar
CLI structure (`compress`, `extract`, `info`) so they can be benchmarked
side-by-side.

| Tool | Focus | Why it Matters |
| :--- | :--- | :--- |
| ` | Streaming pipelines | Pipes the tar writer straight into the compressor so multi-terabyte datasets can be archived with constant memory usage. Metadata retains timing and integrity stats for benchmarking. |
| `| Global deduplication | Splits files into hashed blocks, stores each block once, and replays them via a manifest. Great for corpora with repeated checkpoints or dataset shards. |
|  | SQLite content lake | Persists chunks in a queryable SQLite database and exposes an HTTP API for chunk streaming—ideal for orchestrating LLM training clusters. |

All three scripts live at the repository root and can be executed
directly, e.g. `python gmw_tool_v3.py compress dataset dedup.gmw`.

-----


<img width="1491" height="1055" alt="0c3751e7-0c71-4302-97db-0bb2f0afab06" src="https://github.com/user-attachments/assets/071182c6-b20f-4fe1-b57b-9e060b8efc33" />


## 📊 Historical 2025 Performance Highlights

The following benchmarks demonstrate Rat-Trap's ability to maximize speed while maintaining excellent compression. The GMW structure outperforms all tested alternatives for high-volume Image and Audio data.

| Data Type | Best GMW Time | Fastest Competitor | Speed Difference | Best GMW Ratio | Best Overall Ratio |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Image** | **$\mathbf{1.31s}$ (ZSTD-1)** | Pure ZSTD ($3.31s$) | **$2.5\times$ faster** | $1.08$ (ZSTD-9) | $1.33$ (`tar.xz`) |
| **Audio** | **$\mathbf{8.82s}$ (ZSTD-3)** | `tar.gz` ($36.04s$) | **$4.1\times$ faster** | $1.41$ (ZSTD-9) | $1.65$ (`Brotli`) |
| **Text** | $0.047s$ (ZSTD-1) | **LZ4 ($\mathbf{0.0066s}$)** | Slower; the smallest GMW output was **$1.80\times$ smaller** than raw LZ4. | $2.80$ (ZSTD-9) | $3.39$ (`tar.bz2`) |
| **Structured** | $0.035s$ (ZSTD-3) | **LZ4 ($\mathbf{0.0103s}$)** | Slower, but **$1.6\times$ smaller** file size. | $10.04$ (ZSTD-9) | $16.86$ (`tar.bz2`) |

  * **The Crux:** In this historical matrix, Rat-Trap recorded the fastest folder-archive creation for Image and Audio. For Text and Structured data, raw LZ4 was faster but did not preserve equivalent archive semantics, while GMW produced smaller output.

-----

## 🔬 Real-World Impact

Rat-Trap is an **economic advantage.**

Selected historical cells recorded archive-creation speedups as high as
$\mathbf{93.68\times}$. At large scale, reducing compression and I/O time can
lower operating costs and shorten data-handling workflows; actual savings
depend on the workload, hardware, storage, and deployment.

-----

## 🧬 About Motion-TimeSpace (MTS)

Rat-Trap is built on the **Motion-TimeSpace physics framework**, which treats **motion, resistance, and curvature** as the foundation of physical processes—including information. By applying these principles to data compression, Rat-Trap **mimics entropy diffusion** and achieves efficiency limits traditional, purely mathematical algorithms miss.

-----

## 🧑‍🔬 Credits

  * **Rat-Trap** — Core compression tool designed and built by **Glyn Evans**
  * **Physics Engine** — Based on **Motion-TimeSpace Theory (MTS)** by **Martin Ollett**

-----

## 🪤 License

Rat-Trap is free for personal and academic use. For commercial use or integration into proprietary platforms, please [contact us] ollett123123@outlook.com.


⸻

1. High-Level Architecture Overview

                   ┌──────────────────────────────────────┐
                   │    GMW: GEOMETRIC MOTION WRAPPER     │
                   │        (SQLite Archive Engine)       │
                   └──────────────────────────────────────┘

   ┌──────────┐       ┌───────────┐      ┌────────────┐       ┌──────────────┐
   │  Folder  │──────▶│ Chunking  │─────▶│ Compression │──────▶│ SQLite Store │
   └──────────┘       └───────────┘      └────────────┘       └──────────────┘
                             │                   │                    │
                             │                   │                    ▼
                             │                   │         ┌─────────────────────┐
                             ▼                   │         │   Metadata Tables   │
                     ┌────────────────┐          │         │ (files, chunks, meta)│
                     │  Z-Order (ΦΓ)  │◀─────────┘         └─────────────────────┘
                     └────────────────┘


⸻

2. Data Flow: Folder → Chunking → Compression → SQLite

┌──────────────────────────────────────────────────────────────────────────────┐
│                               INGEST PIPELINE                                │
└──────────────────────────────────────────────────────────────────────────────┘

[FOLDER]
   |
   ├─ Read file paths
   ▼
[CHUNK BUILDER]
   - Read 512KB / 1MB blocks
   - Compute BLAKE2b(16) digest
   - Dedup check (exist? skip storage)
   |
   ▼
[MTS GEOMETRIC ORDERING]
   Apply Z-Order Curve (Morton Index)
   Reorder chunks for maximal locality
   |
   ▼
[COMPRESSOR]
   - zstd (default)
   - zlib fallback
   |
   ▼
[SQLITE ARCHIVE]
   - chunks table
   - files table
   - metadata table


⸻

3. Z-Order (Morton) Encoding Pipeline Diagram

┌─────────────────────┐
│   File Metadata      │
│ (path, mtime, size)  │
└──────────┬───────────┘
           |
           ▼
    ┌───────────────┐
    │ Key Generator │
    │  Φ = motion   │
    └──────┬────────┘
           |
           ▼
   ┌────────────────┐
   │ Morton Encoder │  <--- Interleave bits into Z-curve
   │ (Z-Order map)  │
   └────────────────┘
           |
           ▼
  [GEOMETRIC SORTED ORDER]


⸻

4. Chunk Map Visualization (SQLite)

┌────────────────────────────── SQLite: chunks table ───────────────────────────────┐
│ id (TEXT)         compressor   raw_size   data(BLOB)                              │
├────────────────────────────────────────────────────────────────────────────────────┤
│ 9fa21...          "zstd"       524288     <compressed blob>                       │
│ 01bb3...          "zstd"       524288     <compressed blob>                       │
│ a91f0...          "zstd"       183920     <compressed blob>                       │
│ ...                                                                            ...│
└────────────────────────────────────────────────────────────────────────────────────┘

Representation:

[Chunk ID] → [Block of compressed bytes]
      │
      └── referenced by files.chunk_ids[]


⸻

5. File Entry Reconstruction Diagram

┌─────────────────────────────────────────────┐
│                 files table                 │
├─────────────────────────────────────────────┤
│ path: "images/cat001.png"                   │
│ size: 1,048,576                             │
│ chunk_ids: ["9fa21...", "01bb3..."]         │
│ chunk_sizes: [524288, 524288]               │
└─────────────────────────────────────────────┘

     RECONSTRUCTION:

   chunk_ids[0] → decompress → write first 524288 bytes
   chunk_ids[1] → decompress → write next 524288 bytes


⸻

6. Parallel Bucket Compression Layout

      BEFORE ORDERING                          AFTER Z-ORDERING
┌──────┬───────┬────────┬──────┬─────┐     ┌──────┬──────┬──────┬──────┬──────┐
│ A001 │ Z019  │ G3004  │ B002 │ C1F │ --> │ A001 │ A002 │ A003 │ A004 │ A005 │
└──────┴───────┴────────┴──────┴─────┘     └──────┴──────┴──────┴──────┴──────┘
                                                 │      │      │      │
                                                 ▼      ▼      ▼      ▼
                                       ┌───────────── Parallel Buckets ────────────┐
                                       │   B1   │   B2   │   B3   │      B4         │
                                       └────────┴────────┴────────┴─────────────────┘

Each bucket compressed independently → TRUE parallel compression.

⸻

7. Extract Pipeline Diagram

┌──────────────────────────────────────────────┐
│              EXTRACTION PIPELINE             │
└──────────────────────────────────────────────┘

[SQLite Archive]
   |
   ├─ SELECT * FROM files ORDER BY ordering
   |
   ▼
[File Entry]
   |
   ├─ for each chunk_id:
   |      SELECT data FROM chunks
   |      decompress()
   |      write bytes
   |
   ▼
[Reconstructed File]


⸻

8. HTTP Chunk Server Routing Diagram

                GMW HTTP SERVER
    ┌──────────────────────────────────┐
    │ GET /manifest                   │
    │   → returns metadata + file map │
    ├──────────────────────────────────┤
    │ GET /chunks/<chunk_id>          │
    │   → returns compressed blob      │
    └──────────────────────────────────┘

CLIENT FLOW:

    /manifest
       ▼
   get chunk_ids[]
       ▼
  fetch /chunks/<id>
       ▼
 decompress + assemble


⸻

9. GMW vs tar.gz Pipeline Comparison

                    TRADITIONAL PIPELINE
┌────────────┐      ┌──────────────┐      ┌──────────────┐
│   Folder   │ ---> │   tarball    │ ---> │ gzip / xz     │
└────────────┘      └──────────────┘      └──────────────┘
      1 core used        SEQUENTIAL            SEQUENTIAL

                   GMW GEOMETRIC PIPELINE
┌────────────┐     ┌─────────────┬─────────────┬─────────────┐
│   Folder   │ --> │ Chunking    │ Z-Ordering  │ Parallel     │
└────────────┘     └─────────────┴─────────────┴─────────────┘
                                       │
                                       ▼
                                 [SQLite Lake]
             MULTI-CORE PARALLELISM, NO TARBALL, FAST I/O


⸻

