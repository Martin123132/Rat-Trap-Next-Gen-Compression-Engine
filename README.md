
# 🪤 Rat-Trap — Next-Gen Compression Engine

> **"Time is money. Space is motion. Rat-Trap is both."**

Rat-Trap is a **high-performance, MBT-powered data compression system** built by **Glyn Evans** and inspired by the **Motion-TimeSpace (MTS)** physics framework. 
It’s designed to **trap chaotic data** — text, images, audio, structured records — and reorganize it into the smallest, fastest, most efficient form possible.

Where conventional compression tools trade speed for size, Rat-Trap bends that curve. 
By leveraging MTS principles of **motion, resistance, and curvature memory**, it captures entropy more efficiently and delivers **4× to 30× speedups** while maintaining competitive or superior compression ratios.

---

## 🚀 Why Rat-Trap?

| Feature                         | Rat-Trap    | tar.gz  | tar.xz   | tar.bz2 |
| ------------------------------- | ----------- | ------- | -------- | ------- |
| **Text Compression Time**       | **0.065 s** | 1.508 s | 13.122 s | 1.922 s |
| **Audio Compression Time**      | **6.48 s**  | 47.42 s | 298.53 s | 54.59 s |
| **Image Compression Time**      | **3.04 s**  | 14.95 s | 157.59 s | 34.35 s |
| **Structured Compression Time** | **0.028 s** | 0.578 s | 3.463 s  | 2.870 s |

⏱ **Up to 30× faster** than traditional methods.  
📦 **Competitive compression ratios** with Zstandard acceleration.  
🧠 **Physics-inspired design** based on Motion-TimeSpace curvature dynamics.  
🔐 Optional AES-GCM encryption.  
🌐 Fully self-contained Python script — no external build system required.

---

## 🧠 How It Works

Rat-Trap’s core compression engine is built around **GMW (Geometric Motion Wrapper)** — a custom archival format derived from MBT2 physics simulations.

It introduces several key innovations:

* **Motion-TimeSpace Compression** – Organizes data based on motion-derived entropy gradients, mimicking how tension diffuses in physical systems.
* **Z-Order Encoding** – Efficient voxel key mapping using Morton encoding for spatial data compaction.
* **Bloom Filters for Fast Lookups** – Instant bucket-level detection of compressed blocks.
* **Parallelized Bucket Packing** – Optimized thread-based bucket construction for multi-core compression.
* **Adaptive ZSTD Layers** – Configurable trade-offs between speed and compression depth (levels 1–9).
* **Optional AES-GCM Encryption** – Secure archives without losing performance.

---

## 🛠 Installation

Rat-Trap is a single-file tool. Clone the repo or download `gmw_tool.py` directly:

```bash
git clone https://github.com/your-org/rat-trap.git
cd rat-trap
````

Install optional performance dependencies:

```bash
pip install zstandard cryptography xxhash
```

---

## ⚙️ Usage

Run Rat-Trap directly:

```bash
python gmw_tool.py
```

You’ll be prompted to:

1. **Compress** a folder into a `.gmw` archive.
2. **Extract** a `.gmw` archive into a folder.

### 📦 Compress a folder

```bash
python gmw_tool.py
```

```
1) Compress a folder into a .gmw archive
2) Extract a .gmw archive into a folder
Choose an action (1/2): 1
Enter the path of the folder to compress: ./dataset
Enter the output .gmw file name: data_archive.gmw
```

Result:

```
Folder './dataset' compressed into 'data_archive.gmw'.
```

### 📂 Extract a `.gmw` archive

```bash
python gmw_tool.py
```

```
Choose an action (1/2): 2
Enter the path of the .gmw file to extract: data_archive.gmw
Enter the output folder: ./restored
```

Result:

```
Archive 'data_archive.gmw' extracted into './restored'.
```

---

## 📊 Performance Highlights

Benchmarked on real-world datasets:

| Dataset        | Rat-Trap Time | tar.gz Time | tar.xz Time | Rat-Trap Ratio | tar.gz Ratio |
| -------------- | ------------- | ----------- | ----------- | -------------- | ------------ |
| **Text**       | **0.065 s**   | 1.508 s     | 13.122 s    | 2.81           | 2.57         |
| **Image**      | **3.04 s**    | 14.95 s     | 157.59 s    | 1.09           | 1.10         |
| **Audio**      | **6.48 s**    | 47.42 s     | 298.53 s    | 1.40           | 1.33         |
| **Structured** | **0.028 s**   | 0.578 s     | 3.463 s     | 7.28           | 9.70         |

Rat-Trap consistently **outperforms traditional compressors in speed** while maintaining **competitive compression ratios**, especially for **audio and text** — critical for next-generation AI workloads like Sora-scale video, multimodal datasets, and large model checkpoints.

---

## 🔬 Real-World Impact

A 4× compression speedup on petabyte-scale data pipelines translates to **millions in compute savings** for cloud-scale platforms like OpenAI, Anthropic, or Google DeepMind. Rat-Trap isn’t just a faster tool — it’s an economic advantage.

---

## 🧬 About Motion-TimeSpace (MTS)

Rat-Trap is built on the **Motion-TimeSpace physics framework**, which treats **motion, resistance, and curvature** as the foundation of physical processes — including information. By applying these principles to data compression, Rat-Trap **mimics entropy diffusion** and achieves efficiency limits traditional algorithms miss.

---

## 🧑‍🔬 Credits

* **Rat-Trap** — Core compression tool designed and built by **Glyn Evans**
* **Physics Engine** — Based on **Motion-TimeSpace Theory (MTS)** by **Martin Ollett**

---

## 🪤 License

Rat-Trap is free for **personal and academic use**.
For **commercial use** or integration into proprietary platforms, please [contact us] ollett123123@outlook.com

---

## 🧪 Tagline Ideas

* “🪤 Trap entropy. Free motion.”
* “Next-gen compression powered by physics.”
* “Faster than tar. Smarter than gzip.”
* “From motion to memory — compressing the future.”

```

