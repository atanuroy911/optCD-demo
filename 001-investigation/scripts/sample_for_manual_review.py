"""Draw a reproducible random sample of classified uploads for manual review.

Usage: python scripts/sample_for_manual_review.py [per_category] [seed]
Output: results/manual_review_sample.csv (verdict column filled in by hand,
        see evidence/q1_manual_review.md)
"""
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
per_cat = int(sys.argv[1]) if len(sys.argv) > 1 else 4
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42

rows = list(csv.DictReader(open(ROOT / "results" / "artifacts_paper.csv", encoding="utf-8")))
by_cat = defaultdict(list)
for r in rows:
    by_cat[r["category"]].append(r)

rng = random.Random(seed)
sample = []
for cat in sorted(by_cat):
    pool = by_cat[cat]
    sample += rng.sample(pool, min(per_cat, len(pool)))

with open(ROOT / "results" / "manual_review_sample.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(sample[0].keys()) + ["manual_verdict", "note"])
    w.writeheader()
    for r in sample:
        w.writerow({**r, "manual_verdict": "", "note": ""})
for r in sample:
    print(f"[{r['category']}] {r['repo']} {r['workflow_file']} job={r['job']} name={r['artifact_name']} "
          f"if={r['if']!r} path={r['path'][:60]} | {r['consumer_evidence'][:90]}")
