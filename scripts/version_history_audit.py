"""Map every audited chat template to the developer's own template history.

For the three ungated anchors, walks the developer repo's commit history on
Hugging Face, records every distinct tokenizer_config.json chat_template and
the date it first appeared, then labels each corpus repository's template as
CURRENT, DEV-PRIOR <date>, or NOT-IN-HISTORY. Runs on the HF corpus with and
without the repositories listed in data/raw/contamination_v1.json, and on the
ModelScope corpus.

Output: data/results/version_history_audit_v1.json
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEV_REPOS = {
    "Mistral-7B-Instruct-v0.3": "mistralai/Mistral-7B-Instruct-v0.3",
    "Qwen2.5-7B-Instruct": "Qwen/Qwen2.5-7B-Instruct",
    "Phi-3-mini-4k-instruct": "microsoft/Phi-3-mini-4k-instruct",
}
GATED = ["Llama-3.1-8B-Instruct", "gemma-2-9b-it"]


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def wilson(k: int, n: int, z: float = 1.959964) -> list[float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    n, r1, c1 = a + b + c + d, a + b, a + c
    pmf = lambda k: math.comb(r1, k) * math.comb(n - r1, c1 - k) / math.comb(n, c1)
    p0 = pmf(a)
    return round(sum(pmf(k) for k in range(max(0, c1 - (n - r1)), min(r1, c1) + 1) if pmf(k) <= p0 * (1 + 1e-9)), 3)


def developer_history(repo: str) -> dict[str, dict]:
    commits = requests.get(f"https://huggingface.co/api/models/{repo}/commits/main", timeout=30).json()
    versions: dict[str, dict] = {}
    for c in reversed(commits):
        r = requests.get(f"https://huggingface.co/{repo}/raw/{c['id']}/tokenizer_config.json", timeout=30)
        try:
            tmpl = r.json().get("chat_template")
        except ValueError:
            tmpl = None
        if isinstance(tmpl, str) and sha(tmpl) not in versions:
            versions[sha(tmpl)] = {"first_seen": c["date"][:10], "commit": c["id"], "title": c["title"]}
        time.sleep(0.2)
    return {"n_commits": len(commits), "versions": versions}


def label(h: str, current: str, versions: dict) -> str:
    if h == current:
        return "CURRENT"
    if h in versions:
        return f"DEV-PRIOR {versions[h]['first_seen']}"
    return "NOT-IN-HISTORY"


def audit_hf(entries: list[dict], canonical: dict, hist: dict) -> dict:
    out = {"per_anchor": {}, "pooled_canonical": {}, "popularity": {}}
    tot_div = tot_n = tot_prior = 0
    pop = {"high_popularity": [0, 0], "long_tail": [0, 0]}
    for anchor in list(DEV_REPOS) + GATED:
        rows = [e for e in entries if e["anchor_model"] == anchor]
        if anchor in canonical:
            ref, basis = sha(canonical[anchor]["chat_template"]), "canonical"
        else:
            ref, basis = Counter(e["chat_template_sha256"] for e in rows).most_common(1)[0][0], "modal (gated, unverified)"
        div = [e for e in rows if e["chat_template_sha256"] != ref]
        labels = Counter(label(e["chat_template_sha256"], ref, hist[anchor]["versions"]) for e in div) if anchor in hist else None
        hi = [e for e in rows if e["popularity_bucket"] == "high_popularity"]
        lt = [e for e in rows if e["popularity_bucket"] == "long_tail"]
        dh, dl = sum(e in div for e in hi), sum(e in div for e in lt)
        out["per_anchor"][anchor] = {
            "basis": basis, "n": len(rows), "divergent": len(div), "pct": round(100 * len(div) / len(rows), 1),
            "wilson95": wilson(len(div), len(rows)), "divergent_by_history": dict(labels) if labels else None,
            "divergent_repos": sorted(e["repo_id"] for e in div),
            "high_pop": [dh, len(hi)], "long_tail": [dl, len(lt)],
            "popularity_fisher_p": fisher_two_sided(dh, len(hi) - dh, dl, len(lt) - dl),
        }
        for b, grp, k in [("high_popularity", hi, dh), ("long_tail", lt, dl)]:
            pop[b][0] += k
            pop[b][1] += len(grp)
        if anchor in canonical:
            tot_div += len(div)
            tot_n += len(rows)
            tot_prior += sum(v for k, v in labels.items() if k.startswith("DEV-PRIOR"))
    out["pooled_canonical"] = {
        "divergent": tot_div, "n": tot_n, "pct": round(100 * tot_div / tot_n, 1), "wilson95": wilson(tot_div, tot_n),
        "dev_prior": tot_prior, "dev_prior_pct": round(100 * tot_prior / tot_n, 1), "not_in_history": tot_div - tot_prior,
    }
    out["popularity"] = {"pooled_mixed_basis": pop}
    return out


def main():
    canonical = json.loads((ROOT / "data/raw/canonical_templates_v1.json").read_text())
    contamination = set(json.loads((ROOT / "data/raw/contamination_v1.json").read_text())["hf_corpus_v2"])
    hf = [e for e in json.loads((ROOT / "data/results/static_audit_v2.json").read_text())["entries"]
          if e["source"] == "hf_repo_level"]
    ms = json.loads((ROOT / "data/results/modelscope_corpus_v1.json").read_text())["corpus"]

    hist = {a: developer_history(r) for a, r in DEV_REPOS.items()}

    ms_out = {}
    for anchor in DEV_REPOS:
        rows = [r for r in ms if r["anchor"] == anchor]
        cur = sha(canonical[anchor]["chat_template"])
        ms_out[anchor] = {
            "n": len(rows),
            "by_history": dict(Counter(label(r["chat_template_sha256"], cur, hist[anchor]["versions"]) for r in rows)),
            "not_in_history_repos": sorted(r["repo_id"] for r in rows
                                           if label(r["chat_template_sha256"], cur, hist[anchor]["versions"]) == "NOT-IN-HISTORY"),
        }

    result = {
        "generated": time.strftime("%Y-%m-%d"),
        "developer_history": hist,
        "hf_as_published": audit_hf(hf, canonical, hist),
        "hf_contamination_removed": audit_hf([e for e in hf if e["repo_id"] not in contamination], canonical, hist),
        "contamination_excluded": sorted(contamination),
        "modelscope": ms_out,
    }
    path = ROOT / "data/results/version_history_audit_v1.json"
    path.write_text(json.dumps(result, indent=2))
    for k in ("hf_as_published", "hf_contamination_removed"):
        print(k, json.dumps(result[k]["pooled_canonical"]))
    print("modelscope", json.dumps({a: v["by_history"] for a, v in ms_out.items()}))


if __name__ == "__main__":
    main()
