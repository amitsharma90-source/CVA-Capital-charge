"""Phase 3 -- K_reduced (and reduced-version capital / RWA).

MAR50.14:  K_reduced = sqrt( (rho * Sigma_c SCVA_c)^2 + (1-rho^2) * Sigma_c SCVA_c^2 ).
MAR50.14/50.20: Capital = DS * K;  MAR50.1: RWA = 12.5 * Capital.
Consumes Phase 2's per-counterparty SCVA.
"""
from __future__ import annotations

import os
import math
import pandas as pd

import config_loader as cfg
from phase_snapshot import write_phase_snapshot
from phase2_scva import run_phase2

ROOT = cfg.ROOT
OUT_XLSX = os.path.join(ROOT, "Output", "phase3_k_reduced.xlsx")


def k_reduced_from_scva(scva: pd.Series, rho: float) -> dict:
    sum_scva = float(scva.sum())
    sum_scva_sq = float((scva ** 2).sum())
    systematic = (rho * sum_scva) ** 2
    idiosyncratic = (1.0 - rho ** 2) * sum_scva_sq
    k = math.sqrt(systematic + idiosyncratic)
    return {
        "sum_scva": sum_scva,
        "sum_scva_squared": sum_scva_sq,
        "systematic_term": systematic,
        "idiosyncratic_term": idiosyncratic,
        "k_reduced": k,
    }


def run_phase3(write_snapshot: bool = True, phase2_out: pd.DataFrame | None = None) -> pd.DataFrame:
    constants = cfg.load_constants()
    rho = float(constants["rho"])
    ds = float(constants["discount_scalar_DS"])
    rwa_scalar = float(constants["rwa_scalar"])

    cps = run_phase2(write_snapshot=False) if phase2_out is None else phase2_out.copy()

    res = k_reduced_from_scva(cps["scva_per_cp"], rho)
    capital = ds * res["k_reduced"]
    rwa = rwa_scalar * capital

    out = pd.DataFrame([{
        **res,
        "DS": ds,
        "capital_reduced": capital,
        "rwa_reduced": rwa,
    }])

    audit_df = pd.DataFrame([{
        "k_reduced_calc": (
            f"K_reduced = sqrt(({rho:g}*{res['sum_scva']:.4f})^2 + "
            f"(1-{rho:g}^2)*{res['sum_scva_squared']:.4f}) "
            f"= sqrt({res['systematic_term']:.4f} + {res['idiosyncratic_term']:.4f}) "
            f"= {res['k_reduced']:.4f}"
        ),
        "capital_calc": f"Capital = DS*K = {ds:g}*{res['k_reduced']:.4f} = {capital:.4f}",
        "rwa_calc": f"RWA = {rwa_scalar:g}*Capital = {rwa_scalar:g}*{capital:.4f} = {rwa:.4f}",
    }])

    l2 = math.sqrt(res["sum_scva_squared"])
    recon = pd.DataFrame({
        "item": ["k_reduced_le_sum_scva", "k_reduced_ge_l2norm", "rwa_identity_holds"],
        "value": [
            bool(res["k_reduced"] <= res["sum_scva"] + 1e-9),
            bool(res["k_reduced"] >= l2 - 1e-9),
            bool(abs(rwa - rwa_scalar * ds * res["k_reduced"]) < 1e-9),
        ],
    })

    if write_snapshot:
        os.makedirs(os.path.dirname(OUT_XLSX), exist_ok=True)
        write_phase_snapshot(
            OUT_XLSX,
            phase_number=3,
            phase_name="K_reduced",
            mar_clause="MAR50.14, MAR50.1",
            source_module="phase3_k_reduced.py",
            input_source="previous phase output (phase2_scva.py)",
            df_input=cps,
            df_output=out,
            audit={"per_cp_scva": cps, "k_reduced_assembly": audit_df},
            reconciliation=recon,
            notes="rho, DS, 12.5 from config. Single-CP-no-hedge => K==SCVA (see golden).",
        )
    return out


if __name__ == "__main__":
    out = run_phase3()
    print(f"wrote {OUT_XLSX}\n")
    print(out.to_string(index=False))
