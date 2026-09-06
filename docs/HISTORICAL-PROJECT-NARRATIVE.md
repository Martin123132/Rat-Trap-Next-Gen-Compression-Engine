# Rat-Trap historical project narrative and provenance

Status: preserved historical and technical context, separate from the
commercial product page

This document records how Rat-Trap arrived, where its original positioning
came from and where the preserved benchmark evidence lives. It is not a
Microsoft Store listing and does not turn a historical benchmark into a
current universal claim.

## Project provenance

Martin Ollett published Motion-TimeSpace ideas, experiments and code. Glyn
Evans contacted Martin, proposed building a compressor drawing on that work,
asked permission and supplied a written agreement. Glyn later returned with
Rat-Trap.

The Rat-Trap compressor implementation was designed and built by **Glyn
Evans**, drawing on Motion-TimeSpace work by **Martin Ollett**. Rat-Trap is now
recorded as a product owned and published by **TWO HANDS NETWORK LTD** under
its written agreements with the project's contributors.

That provenance is kept intact. The benchmark programme evaluates what the
software actually does on named workloads. It is not presented as proof or
disproof of a complete physics framework.

## Why the public README changed

The original README combined several different things:

- product promotion;
- historical benchmark tables;
- competitor comparisons;
- implementation notes;
- Motion-TimeSpace explanations;
- experimental tooling; and
- architecture sketches.

Those materials serve technical and historical readers, but they obscured the
customer-facing product. Rat-Trap now uses two coordinated lanes:

1. a front page about Rat-Trap's own customer value; and
2. a diligence lane containing complete evidence, limitations and history.

Separating the lanes does not retract the history. It makes the purpose and
evidence status of each claim clearer.

## Preserved benchmark material

The main evidence records are:

- [`BENCHMARK-AUDIT.md`](../BENCHMARK-AUDIT.md);
- [`BENCHMARK-HISTORY.md`](BENCHMARK-HISTORY.md);
- [`PRODUCT-EVIDENCE-LANES.md`](PRODUCT-EVIDENCE-LANES.md);
- the [full-run transcript](../historical/benchmarking-2.0-full-run.txt);
- the [original benchmark harness](../historical/rat-trap-2.0-benchmark.txt);
- the [preserved original implementations](../historical/README.md); and
- machine-readable records under `benchmarks/`.

They preserve successful, losing, failed, rounded and incomplete results
rather than keeping only favourable cells.

## Evidence status

The recorded 2025 campaign contains genuine measurements, including
workload-specific Rat-Trap speed wins. It also has limitations:

- most cells have one trial;
- hardware and dependency details were not fully captured;
- datasets were not frozen with complete content hashes and manifests;
- timing boundaries were not identical for every method;
- some raw-codec comparisons did not provide equivalent archive semantics;
- some later engine families differ materially from the earlier tar-plus-Zstd
  engine; and
- several old marketing sentences broadened individual cells beyond what the
  preserved matrix supports.

For those reasons, old numerical claims are labelled historical and scoped.
Current commercial copy contains no benchmark number unless a new,
release-hardware run supports it end to end.

## Original long-form README

The previous long-form narrative remains recoverable from Git history. In this
working tree, the last committed version can be inspected with:

```text
git show e5d14320b919e0081dd92beac3090950f95d5d8b:README.md
```

The earlier GitHub history also retains the README and benchmark campaign as
they evolved. This historical preservation is intentional.

## Credits

- **Rat-Trap compressor implementation:** Glyn Evans
- **Motion-TimeSpace work:** Martin Ollett
- **Product owner and publisher:** TWO HANDS NETWORK LTD
