"""Pre-registered analysis of the blinded Mistral hand labels (see PREREGISTRATION.md).

Usage: python analyze.py hand_labels.csv
Writes hand_label_results.json next to this script and prints a summary.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

from items import HERE, load_items, manifest_sha256

LABELS = {"REFUSE", "COMPLY", "UNDETERMINED"}
ALPHA = 0.05
PRIOR = HERE.parents[2] / "data" / "results" / "hand_validation_labeled_v2.json"
PRIOR_CONDITION = {"A_no_system": "A", "B_with_system": "B", "C_no_system": "C"}


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * (c - h), 100 * (c + h))


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def resolve(label: str, undet_as: str | None) -> str | None:
    if label == "UNDETERMINED":
        return undet_as
    return label


def condition_rates(by_cond: dict, undet_as: str | None) -> dict:
    out = {}
    for cond, labels in by_cond.items():
        vals = [resolve(l, undet_as) for l in labels]
        vals = [v for v in vals if v is not None]
        k = sum(v == "REFUSE" for v in vals)
        lo, hi = wilson(k, len(vals))
        out[cond] = {"n": len(vals), "refuse": k, "rate_pct": round(100 * k / len(vals), 1) if vals else None,
                     "wilson95": [round(lo, 1), round(hi, 1)]}
    return out


def paired(pairs: dict, hi: str, lo: str, undet_as: str | None) -> dict:
    b = c = n = 0
    for prompt, conds in pairs.items():
        x, y = resolve(conds[hi], undet_as), resolve(conds[lo], undet_as)
        if x is None or y is None:
            continue
        n += 1
        if x == "REFUSE" and y == "COMPLY":
            b += 1
        elif x == "COMPLY" and y == "REFUSE":
            c += 1
    p = mcnemar_exact(b, c)
    return {"comparison": f"{hi} vs {lo}", "pairs_used": n, f"{hi}_refuse_only": b, f"{lo}_refuse_only": c,
            "paired_effect_pp": round(100 * (b - c) / n, 1) if n else None,
            "mcnemar_exact_p": round(p, 4)}


def overlap(r1: dict, r2: dict) -> bool:
    return not (r1["wilson95"][0] > r2["wilson95"][1] or r2["wilson95"][0] > r1["wilson95"][1])


def kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def main(path: str):
    items = load_items()
    rows = {r["id"]: r for r in csv.DictReader(open(path, newline=""))}
    missing = [it["id"] for it in items if not rows.get(it["id"], {}).get("label")]
    bad = {r["label"] for r in rows.values() if r["label"] and r["label"] not in LABELS}
    if missing or bad:
        sys.exit(f"incomplete or invalid labels: {len(missing)} missing, unknown values {bad}")

    by_cond = {"A": [], "B": [], "C": []}
    pairs: dict[str, dict] = {}
    confusion = {cond: Counter() for cond in "ABC"}
    for it in items:
        lab = rows[it["id"]]["label"]
        by_cond[it["condition"]].append(lab)
        pairs.setdefault(it["prompt"], {})[it["condition"]] = lab
        clf = "REFUSE" if it["classifier_refused"] else "COMPLY"
        confusion[it["condition"]][f"classifier_{clf}->hand_{lab}"] += 1

    result = {"manifest_sha256": manifest_sha256(items), "label_counts": {c: dict(Counter(v)) for c, v in by_cond.items()}}
    for name, undet_as in [("primary_undetermined_excluded", None),
                           ("sensitivity_undetermined_as_refuse", "REFUSE"),
                           ("sensitivity_undetermined_as_comply", "COMPLY")]:
        rates = condition_rates(by_cond, undet_as)
        result[name] = {
            "rates": rates,
            "B_vs_C": {**paired(pairs, "B", "C", undet_as), "wilson_overlap": overlap(rates["B"], rates["C"])},
            "A_vs_C": {**paired(pairs, "A", "C", undet_as), "wilson_overlap": overlap(rates["A"], rates["C"])},
            "B_vs_A": {**paired(pairs, "B", "A", undet_as), "wilson_overlap": overlap(rates["B"], rates["A"])},
        }

    def outcome_of(cmp: dict) -> str:
        eff, p = cmp["paired_effect_pp"], cmp["mcnemar_exact_p"]
        if eff is not None and eff > 0 and p < ALPHA:
            return "HOLDS"
        if eff is not None and eff > 0:
            return "NOT_CONFIRMED"
        return "NO_EFFECT"

    outcomes = {k: outcome_of(result[k]["B_vs_C"]) for k in (
        "primary_undetermined_excluded", "sensitivity_undetermined_as_refuse", "sensitivity_undetermined_as_comply")}
    result["decision"] = {
        "outcome": outcomes["primary_undetermined_excluded"],
        "sensitivity_outcomes": outcomes,
        "robust_to_undetermined_handling": len(set(outcomes.values())) == 1,
    }
    result["classifier_vs_hand"] = {c: dict(v) for c, v in confusion.items()}

    prior = json.loads(PRIOR.read_text())["items"]
    by_text = {(it["condition"], it["output"]): rows[it["id"]]["label"] for it in items}
    a, b = [], []
    for r in prior:
        cond = PRIOR_CONDITION.get(r["condition"])
        if "mistral" not in r["source"] or cond is None or r["hand_label_refused"] is None:
            continue
        now = by_text.get((cond, r["output"]))
        if now is None or now == "UNDETERMINED":
            continue
        a.append("REFUSE" if r["hand_label_refused"] else "COMPLY")
        b.append(now)
    result["intra_rater_vs_prior_spot_check"] = {
        "n_matched": len(a), "agreement_pct": round(100 * sum(x == y for x, y in zip(a, b)) / len(a), 1) if a else None,
        "cohens_kappa": kappa(a, b)}

    (HERE / "hand_label_results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(HERE / "hand_labels.csv"))
