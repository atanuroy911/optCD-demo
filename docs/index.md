---
title: OptCD
---

# OptCD: Optimizing Continuous Development

OptCD finds files that a CI build creates but never uses — a test report
nobody reads, a comparison artifact nobody uploads — and automatically fixes
the build command so it stops wasting time generating them.

This site explains the whole thing from scratch: no prior knowledge of the
tool, the paper, or CI internals assumed.

- **[How it works](how-it-works.md)** — the mechanism, step by step, in plain language.
- **[Architecture](architecture.md)** — the five components (Logger, Classifier, Clusterer, Mapper, Fixer) and how data flows between them, mapped to the actual code.
- **[Running it](running-it.md)** — how to set it up and run it yourself, including the Windows-specific gotchas we hit.
- **[Findings & limitations](findings.md)** — gaps, bugs, and edge cases discovered while replicating the paper's results.

## Origin

OptCD is a research tool from the paper:

> T. Baral, E. Oğul, S. Rahman, A. Shi, W. Lam. **"OptCD: Optimizing Continuous
> Development."** 2025 IEEE/ACM 47th International Conference on Software
> Engineering: Companion Proceedings (ICSE-Companion), 2025.
> DOI: [10.1109/ICSE-Companion66252.2025.00021](https://doi.org/10.1109/ICSE-Companion66252.2025.00021)

The full paper PDF is included in this repo at https://dl.acm.org/doi/10.1109/ICSE-Companion66252.2025.00021
Everything on this site is our own explanation of the paper and the codebase —
if anything here and the paper disagree, the paper is the source of truth for
the research claims; this site is the source of truth for "what does this
specific codebase actually do."
