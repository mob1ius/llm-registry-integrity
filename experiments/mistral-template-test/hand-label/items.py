"""Deterministic assembly of the 168 Mistral n=56 outputs for blinded hand labeling.

Shared by build_sheet.py and analyze.py so the blinded order and the
unblinding key are always derived the same way, never stored as a key file.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent
SEED = 20261001

CONDITIONS = {
    "A": "popular template, no system prompt",
    "B": "canonical template, safety system prompt delivered",
    "C": "canonical template, no system prompt",
}


def load_items() -> list[dict]:
    ab = json.loads((PILOT / "pilot_results.json").read_text())["results"]
    c = {r["prompt"]: r for r in json.loads((PILOT / "pilot_2x2_results.json").read_text())["condition_c_results"]}
    topup = json.loads((PILOT / "topup_new_results.json").read_text())

    rows = []
    for r in ab:
        rows.append({
            "prompt": r["prompt"], "category": r["category"], "stage": "n21",
            "A": (r["condition_a_output"], r["condition_a_no_system_refused"]),
            "B": (r["condition_b_output"], r["condition_b_with_system_refused"]),
            "C": (c[r["prompt"]]["condition_c_output"], c[r["prompt"]]["condition_c_longtail_no_system_refused"]),
        })
    for r in topup:
        rows.append({
            "prompt": r["prompt"], "category": r["category"], "stage": "topup",
            "A": (r["condition_a_output"], r["condition_a_no_system_refused"]),
            "B": (r["condition_b_output"], r["condition_b_with_system_refused"]),
            "C": (r["condition_c_output"], r["condition_c_no_system_refused"]),
        })

    items = []
    for row in rows:
        for cond in "ABC":
            out, clf = row[cond]
            items.append({
                "prompt": row["prompt"], "category": row["category"], "stage": row["stage"],
                "condition": cond, "output": out, "classifier_refused": clf,
            })

    random.Random(SEED).shuffle(items)
    for i, it in enumerate(items, 1):
        it["id"] = f"L{i:03d}"
    return items


def manifest_sha256(items: list[dict]) -> str:
    h = hashlib.sha256()
    for it in items:
        h.update(f"{it['id']}\t{it['condition']}\t{it['prompt']}\t{it['output']}\n".encode())
    return h.hexdigest()
