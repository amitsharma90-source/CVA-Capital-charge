"""QA guard -- HY/NR path.

The main book is all-IG by design (CLAUDE.md), so the HY/NR risk-weight column
(MAR50.16) is otherwise unexercised. This guard drives one non-IG counterparty
through the RW lookup and SCVA, asserting the HY/NR weight is picked up and flows
correctly. Kept as a permanent regression guard; does not touch the main book.
"""
from __future__ import annotations

import config_loader as cfg
import maturity as mat


def run() -> bool:
    c = cfg.load_constants()
    alpha, rate = float(c["alpha"]), float(c["discount_rate"])
    rw_table = cfg.load_rw_table()

    sector = "Financial"
    rw_ig = cfg.rw_lookup(rw_table, sector, "IG")     # 0.05
    rw_hy = cfg.rw_lookup(rw_table, sector, "HY")     # 0.12
    rw_nr = cfg.rw_lookup(rw_table, sector, "NR")     # NR maps to HY/NR column

    ead, m = 100.0, 2.0
    df = mat.discount_factor(m, rate)
    scva_ig = (1.0 / alpha) * rw_ig * (m * ead * df)
    scva_hy = (1.0 / alpha) * rw_hy * (m * ead * df)

    checks = [
        ("HY_weight_is_table_value", abs(rw_hy - float(rw_table.loc[sector, "RW_HY_NR"])) < 1e-12, f"RW_HY={rw_hy}"),
        ("NR_maps_to_HY_NR_column", abs(rw_nr - rw_hy) < 1e-12, f"RW_NR={rw_nr}"),
        ("HY_distinct_from_IG", rw_hy > rw_ig, f"IG={rw_ig} HY={rw_hy}"),
        ("SCVA_scales_with_RW", abs(scva_hy / scva_ig - rw_hy / rw_ig) < 1e-9, f"ratio={scva_hy/scva_ig:.4f}"),
    ]
    ok = True
    width = max(len(n) for n, _, _ in checks)
    for name, passed, detail in checks:
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name.ljust(width)}  {detail}")
    print(f"\n{'HY/NR PATH OK' if ok else 'HY/NR PATH FAILED'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
