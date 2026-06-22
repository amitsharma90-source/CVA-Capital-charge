"""QA suite -- goldens + structural invariants for the BA-CVA engine.

Run after a full pipeline run. Compares against versioned golden fixtures
(Model/golden/) and asserts the regulatory invariants. No capital numbers are
pinned in prose -- they live in the JSON fixtures.
"""
from __future__ import annotations

import os
import json
import math
import pandas as pd

import config_loader as cfg
import maturity as mat
from phase2_scva import run_phase2
from phase3_k_reduced import k_reduced_from_scva
from phase4_hedges import run_phase4
from phase5_k_full import k_hedged

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden")
_results: list[tuple[str, bool, str]] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, bool(ok), detail))


def golden_1_single_cp() -> None:
    """Pure-math single-CP-no-hedge fixture; independent hand-derived lock."""
    g = json.load(open(os.path.join(GOLDEN, "golden1_single_cp.json")))
    inp, exp, tol = g["inputs"], g["expected"], g["tolerance"]
    c = cfg.load_constants()
    rho, ds, rwa_scalar = float(c["rho"]), float(c["discount_scalar_DS"]), float(c["rwa_scalar"])
    rate = float(c["discount_rate"]); alpha = float(c["alpha"])
    rw = cfg.rw_lookup(cfg.load_rw_table(), inp["sector"], inp["credit_quality"])

    df = mat.discount_factor(inp["M_NS"], rate)
    scva = (1.0 / alpha) * rw * (inp["M_NS"] * inp["EAD_NS"] * df)
    k = k_reduced_from_scva(pd.Series([scva]), rho)["k_reduced"]
    capital = ds * k
    rwa = rwa_scalar * capital

    _check("golden1_RW", abs(rw - inp["RW_c_expected"]) < tol, f"RW={rw}")
    _check("golden1_DF", abs(df - exp["DF_NS"]) < tol, f"DF={df:.10f}")
    _check("golden1_SCVA", abs(scva - exp["scva"]) < tol, f"SCVA={scva:.10f}")
    _check("golden1_Kreduced", abs(k - exp["k_reduced"]) < tol, f"K={k:.10f}")
    _check("golden1_capital", abs(capital - exp["capital"]) < tol, f"cap={capital:.10f}")
    _check("golden1_RWA", abs(rwa - exp["rwa"]) < tol, f"RWA={rwa:.10f}")
    _check("golden1_RWA_2dp", round(rwa, 2) == exp["rwa_rounded_2dp"], f"RWA2dp={round(rwa,2)}")
    _check("invariant_single_cp_K_eq_SCVA", abs(k - scva) < tol, f"K={k:.8f} SCVA={scva:.8f}")


def golden_2_two_cp_full() -> None:
    """Independent hand-derived two-CP full case; locks K_hedged/K_full algebra."""
    g = json.load(open(os.path.join(GOLDEN, "golden2_two_cp_full.json")))
    ci, exp, tol = g["component_inputs"], g["expected"], g["tolerance"]
    c = cfg.load_constants()
    rho, beta, ds, rwa_scalar = (float(c["rho"]), float(c["beta"]),
                                 float(c["discount_scalar_DS"]), float(c["rwa_scalar"]))
    merged = pd.DataFrame({
        "Counterparty": list(ci["scva"].keys()),
        "scva_per_cp": list(ci["scva"].values()),
        "snh_per_cp": list(ci["snh"].values()),
        "hma_per_cp": list(ci["hma"].values()),
    })
    kred = k_reduced_from_scva(merged["scva_per_cp"], rho)["k_reduced"]
    kh = k_hedged(merged, ih=ci["IH"], rho=rho)["k_hedged"]
    k_full = beta * kred + (1.0 - beta) * kh
    capital = ds * k_full
    rwa = rwa_scalar * capital

    _check("golden2_Kreduced", abs(kred - exp["k_reduced"]) < tol, f"K_red={kred:.6f}")
    _check("golden2_Khedged", abs(kh - exp["k_hedged"]) < tol, f"K_hedged={kh:.6f}")
    _check("golden2_Kfull", abs(k_full - exp["k_full"]) < tol, f"K_full={k_full:.6f}")
    _check("golden2_capital", abs(capital - exp["capital_full"]) < tol, f"cap={capital:.6f}")
    _check("golden2_RWA", abs(rwa - exp["rwa_full"]) < tol, f"RWA={rwa:.6f}")


def invariant_no_hedge_collapse() -> None:
    """Structural lock: with no hedges, K_hedged must equal K_reduced (MAR50.14)."""
    c = cfg.load_constants(); rho = float(c["rho"])
    cps = run_phase2(write_snapshot=False)
    zero = cps[["Counterparty", "scva_per_cp"]].copy()
    zero["snh_per_cp"] = 0.0
    zero["hma_per_cp"] = 0.0
    kh = k_hedged(zero, ih=0.0, rho=rho)["k_hedged"]
    kred = k_reduced_from_scva(cps["scva_per_cp"], rho)["k_reduced"]
    _check("invariant_no_hedge_collapse", abs(kh - kred) < 1e-9, f"K_hedged={kh:.8f} K_reduced={kred:.8f}")


def invariant_direct_hedge_hma_zero() -> None:
    _, _, sn_detail, _ = run_phase4(write_snapshot=False)
    direct = sn_detail.loc[sn_detail["tier"] == "direct", "hma_contrib"]
    _check("invariant_direct_hedge_HMA_zero", bool((direct.abs() < 1e-12).all()),
           f"max|HMA_direct|={direct.abs().max() if len(direct) else 0}")


def invariant_beta_floor() -> None:
    from phase5_k_full import run_phase5
    c = cfg.load_constants(); beta = float(c["beta"])
    out = run_phase5(write_snapshot=False).iloc[0]
    _check("invariant_beta_floor", bool(out["k_full"] >= beta * out["k_reduced"] - 1e-9),
           f"K_full={out['k_full']:.4f} >= beta*K_reduced={beta*out['k_reduced']:.4f}")


def run_all() -> bool:
    _results.clear()
    golden_1_single_cp()
    golden_2_two_cp_full()
    invariant_no_hedge_collapse()
    invariant_direct_hedge_hma_zero()
    invariant_beta_floor()
    width = max(len(n) for n, _, _ in _results)
    all_ok = True
    for name, ok, detail in _results:
        all_ok &= ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    print(f"\n{'ALL GREEN' if all_ok else 'FAILURES PRESENT'} ({sum(o for _,o,_ in _results)}/{len(_results)})")
    return all_ok


if __name__ == "__main__":
    ok = run_all()
    raise SystemExit(0 if ok else 1)
