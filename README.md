# 🪤 Rat-Trap — Next-Gen Compression Engine  

**"Time is money. Space is motion. Rat-Trap is both."**

Rat-Trap is a **high-performance, GMW-powered data compression system** built by Glyn Evans and Martin ollett, inspired by the **Motion-TimeSpace (MTS) physics framework**. It’s engineered to **trap chaotic data**—text, images, audio, structured records—and reorganize it into the smallest, fastest, most efficient form possible.

Where conventional compression tools trade speed for size, **Rat-Trap defines the new speed-to-ratio standard.** By leveraging MTS principles of motion, resistance, and curvature memory, it captures entropy more efficiently and delivers **up to $93\times$ speedups** while maintaining competitive or superior compression ratios.

## 🚀 Why Rat-Trap? (The New Standard)

Rat-Trap's GMW format is not just a faster compressor; it's the **undisputed speed leader** for the largest, most critical AI and data science workloads. It renders the long-time standard `tar.gz` obsolete.

| Metric | GMW (ZSTD-3) | Tar/Gzip (Legacy Standard) | Tar/XZ (Slowest/Best Ratio) | Pure ZSTD (Modern Baseline) |
| :--- | :--- | :--- | :--- | :--- |
| **Image Compression Time** | **$\mathbf{2.54s}$** | $11.46s$ | $122.95s$ | $3.31s$ |
| **Speedup (vs. Gzip)** | **$4.5\times$ faster** | $1.0\times$ | $0.09\times$ | $3.5\times$ faster |
| **Audio Compression Time** | **$\mathbf{8.82s}$** | $36.04s$ | $236.70s$ | $1253.34s$ |
| **Speedup (vs. Tar/XZ)** | **$26.8\times$ faster** | $6.6\times$ faster | $1.0\times$ | $0.19\times$ faster |

  * **🥇 The Speed Leader:** GMW-ZSTD-1 is the **fastest archiver tested** for folder-level Image data, beating even bare ZSTD and LZ4.
  * **⏱ Up to $\mathbf{93\times}$ faster** than traditional methods like `tar.xz` (on Image data).
  * **⚖️ The New Default:** GMW-ZSTD is consistently **$4\times$ to $8\times$ faster than `tar.gz`** while achieving better or comparable size.
  * **🧠 Physics-Inspired Design** based on Motion-TimeSpace curvature dynamics.
  * **🌐 Fully self-contained Python script**—no external build system required.

-----

## 🧠 How It Works

Rat-Trap’s core compression engine is built around **GMW (Geometric Motion Wrapper)**—a custom archival format derived from MBT2 physics simulations. It optimizes for file aggregation and parallel processing, solving the I/O bottlenecks that choke traditional compression tools.

Key Innovations:

  * **Motion-TimeSpace Compression** – Organizes data based on motion-derived entropy gradients, mimicking how tension diffuses in physical systems.
  * **Parallelized Bucket Packing** – Optimized thread-based bucket construction for multi-core compression, which is the source of its massive speed advantage over single-stream `tar` pipes.
  * **Z-Order Encoding** – Efficient voxel key mapping using Morton encoding for enhanced spatial data compaction.
  * **Adaptive ZSTD Layers** – Configurable trade-offs between speed and compression depth (levels 1–9) to match specific latency requirements.
  * **Optional AES-GCM Encryption** – Secure archives without losing performance.

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
4.  `rat-trap serve <archive>` – expose the archive via HTTP chunk streaming.

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


## 📊 Performance Highlights

The following benchmarks demonstrate Rat-Trap's ability to maximize speed while maintaining excellent compression. The GMW structure outperforms all tested alternatives for high-volume Image and Audio data.

| Data Type | Best GMW Time | Fastest Competitor | Speed Difference | Best GMW Ratio | Best Overall Ratio |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Image** | **$\mathbf{1.31s}$ (ZSTD-1)** | Pure ZSTD ($3.31s$) | **$2.5\times$ faster** | $1.08$ (ZSTD-9) | $1.33$ (`tar.xz`) |
| **Audio** | **$\mathbf{8.82s}$ (ZSTD-3)** | `tar.gz` ($36.04s$) | **$4.1\times$ faster** | $1.41$ (ZSTD-9) | $1.65$ (`Brotli`) |
| **Text** | $0.047s$ (ZSTD-1) | **LZ4 ($\mathbf{0.0066s}$)** | Slower, but **$4\times$ smaller** file size. | $2.80$ (ZSTD-9) | $3.39$ (`tar.bz2`) |
| **Structured** | $0.035s$ (ZSTD-3) | **LZ4 ($\mathbf{0.0103s}$)** | Slower, but **$1.6\times$ smaller** file size. | $10.04$ (ZSTD-9) | $16.86$ (`tar.bz2`) |

  * **The Crux:** For Image and Audio, Rat-Trap is the fastest archiver by leveraging parallel I/O and GMW structure. For Text and Structured data, it offers a superior trade-off: marginally slower than raw LZ4, but delivering a vastly better (smaller) file size.

-----

## 🔬 Real-World Impact

Rat-Trap is an **economic advantage.**

A $\mathbf{4\times \text{ to } 93\times}$ compression speedup on petabyte-scale data pipelines translates directly to **tens of millions in compute savings** for cloud-scale platforms like OpenAI, Google DeepMind, and Meta. By dramatically reducing I/O wait times, Rat-Trap enables **faster AI model iteration, quicker checkpointing, and lower operational costs.**

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

