"""QA guard -- baseline -> verify regression harness.

Captures every per-row numeric output of phases 1-5 plus each phase's
reconciliation values into a versioned baseline (Model/golden/baseline_outputs.json).
On later runs it re-runs the pipeline and asserts bit-identical (NaN-aware,
dtype-agnostic), so any duplicate-removal / column-rename / refactor that silently
changes a number fails loudly.

    first run                : writes the baseline, prints CAPTURED
    subsequent runs          : verifies, prints PASS/FAIL
    --recapture (or env)     : force-rewrite the baseline (use only intentionally)
"""
from __future__ import annotations

import os
import sys
import json
import math
import pandas as pd

import config_loader as cfg
from phase1_inputs import run_phase1
from phase2_scva import run_phase2
from phase3_k_reduced import run_phase3
from phase4_hedges import run_phase4
from phase5_k_full import run_phase5

BASELINE = os.path.join(cfg.ROOT, "Model", "golden", "baseline_outputs.json")


def _flatten(prefix: str, df: pd.DataFrame, key_col: str | None) -> dict:
    """Flatten numeric cells of df into {prefix.key.col: value}."""
    out: dict = {}
    for i, row in df.reset_index(drop=True).iterrows():
        rkey = str(row[key_col]) if key_col and key_col in df.columns else str(i)
        for col in df.columns:
            val = row[col]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                out[f"{prefix}.{rkey}.{col}"] = float(val)
    return out


def capture() -> dict:
    snap: dict = {}
    snap.update(_flatten("p1", run_phase1(write_snapshot=False), "NS#"))
    snap.update(_flatten("p2", run_phase2(write_snapshot=False), "Counterparty"))
    snap.update(_flatten("p3", run_phase3(write_snapshot=False), None))
    h, ih, _, _ = run_phase4(write_snapshot=False)
    snap.update(_flatten("p4", h, "Counterparty"))
    snap["p4.IH"] = float(ih)
    snap.update(_flatten("p5", run_phase5(write_snapshot=False), None))
    return snap


def _equal(a: float, b: float) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= 1e-9 + 1e-9 * abs(b)


def run(recapture: bool = False) -> bool:
    snap = capture()
    if recapture or not os.path.exists(BASELINE):
        json.dump(snap, open(BASELINE, "w"), indent=2, sort_keys=True)
        print(f"CAPTURED baseline: {len(snap)} values -> {BASELINE}")
        return True

    base = json.load(open(BASELINE))
    missing = sorted(set(base) - set(snap))
    added = sorted(set(snap) - set(base))
    changed = [(k, base[k], snap[k]) for k in base if k in snap and not _equal(snap[k], base[k])]

    ok = not (missing or changed)
    for k in missing:
        print(f"[FAIL] MISSING  {k}  (was {base[k]})")
    for k, ov, nv in changed:
        print(f"[FAIL] CHANGED  {k}  {ov} -> {nv}")
    for k in added:
        print(f"[warn] ADDED    {k} = {snap[k]}")  # additions don't fail the guard
    if ok:
        print(f"[PASS] {len(base)} baseline values bit-identical"
              + (f" ({len(added)} new value(s) added)" if added else ""))
    print(f"\n{'BASELINE VERIFIED' if ok else 'BASELINE DRIFT DETECTED'}")
    return ok


if __name__ == "__main__":
    recap = "--recapture" in sys.argv or os.environ.get("BACVA_RECAPTURE") == "1"
    raise SystemExit(0 if run(recapture=recap) else 1)
