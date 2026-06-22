"""Phase 5 -- K_hedged + K_full + capital + RWA (BA-CVA full version).

MAR50.21-22 (K_hedged), MAR50.20 (K_full, DS), MAR50.1 (RWA).

    K_hedged = sqrt(
        ( rho * Sigma_c (SCVA_c - SNH_c) - IH )^2          # systematic
        + Sigma_c (1 - rho^2) * (SCVA_c - SNH_c)^2          # idiosyncratic
        + Sigma_c HMA_c                                     # indirect-hedge misalignment
    )
    K_full   = beta * K_reduced + (1 - beta) * K_hedged
    Capital  = DS * K_full
    RWA      = 12.5 * Capital

VERIFIED against the MAR50.21 equation image: this matches verbatim -- rho
multiplies (SCVA_c - SNH_c) in the systematic term, IH is subtracted un-scaled,
and (SCVA_c - SNH_c) carries the (1-rho^2) idiosyncratic weight. Locked by the
no-hedge-collapse invariant and Golden 2 in qa_suite.
"""
from __future__ import annotations

import os
import math
import pandas as pd

import config_loader as cfg
from phase_snapshot import write_phase_snapshot
from phase2_scva import run_phase2
from phase3_k_reduced import k_reduced_from_scva
from phase4_hedges import run_phase4


ROOT = cfg.ROOT
OUT_XLSX = os.path.join(ROOT, "Output", "phase5_k_full.xlsx")


def k_hedged(merged: pd.DataFrame, ih: float, rho: float) -> dict:
    """merged carries scva_per_cp, snh_per_cp, hma_per_cp per counterparty."""
    net = merged["scva_per_cp"] - merged["snh_per_cp"]          # SCVA_c - SNH_c
    systematic = (rho * float(net.sum()) - ih) ** 2
    idiosyncratic = (1.0 - rho ** 2) * float((net ** 2).sum())
    sum_hma = float(merged["hma_per_cp"].sum())
    k = math.sqrt(systematic + idiosyncratic + sum_hma)
    return {
        "sum_scva_minus_snh": float(net.sum()),
        "systematic_term": systematic,
        "idiosyncratic_term": idiosyncratic,
        "sum_hma": sum_hma,
        "k_hedged": k,
    }


def run_phase5(write_snapshot: bool = True) -> pd.DataFrame:
    constants = cfg.load_constants()
    rho = float(constants["rho"])
    beta = float(constants["beta"])
    ds = float(constants["discount_scalar_DS"])
    rwa_scalar = float(constants["rwa_scalar"])

    cps = run_phase2(write_snapshot=False)
    hedges, ih, _, _ = run_phase4(write_snapshot=False)

    merged = cps.merge(hedges, on="Counterparty", how="left").fillna(
        {"snh_per_cp": 0.0, "hma_per_cp": 0.0})

    kred = k_reduced_from_scva(merged["scva_per_cp"], rho)["k_reduced"]
    kh = k_hedged(merged, ih, rho)
    k_full = beta * kred + (1.0 - beta) * kh["k_hedged"]
    capital = ds * k_full
    rwa = rwa_scalar * capital

    out = pd.DataFrame([{
        "IH": ih,
        **kh,
        "k_reduced": kred,
        "beta": beta,
        "k_full": k_full,
        "DS": ds,
        "capital_full": capital,
        "rwa_full": rwa,
    }])

    audit_df = pd.DataFrame([{
        "k_hedged_calc": (
            f"K_hedged = sqrt(({rho:g}*{kh['sum_scva_minus_snh']:.4f} - {ih:.4f})^2 "
            f"+ (1-{rho:g}^2)*Sigma(SCVA-SNH)^2 + Sigma_HMA) "
            f"= sqrt({kh['systematic_term']:.4f} + {kh['idiosyncratic_term']:.4f} + {kh['sum_hma']:.4f}) "
            f"= {kh['k_hedged']:.4f}"
        ),
        "k_full_calc": (
            f"K_full = {beta:g}*{kred:.4f} + (1-{beta:g})*{kh['k_hedged']:.4f} = {k_full:.4f}"
        ),
        "capital_calc": f"Capital = {ds:g}*{k_full:.4f} = {capital:.4f}",
        "rwa_calc": f"RWA = {rwa_scalar:g}*{capital:.4f} = {rwa:.4f}",
    }])

    recon = pd.DataFrame({
        "item": ["k_full_ge_beta_k_reduced", "k_hedged_le_k_reduced", "rwa_identity_holds"],
        "value": [
            bool(k_full >= beta * kred - 1e-9),
            bool(kh["k_hedged"] <= kred + 1e-9),
            bool(abs(rwa - rwa_scalar * ds * k_full) < 1e-9),
        ],
    })

    if write_snapshot:
        os.makedirs(os.path.dirname(OUT_XLSX), exist_ok=True)
        write_phase_snapshot(
            OUT_XLSX,
            phase_number=5,
            phase_name="K_hedged + K_full + RWA",
            mar_clause="MAR50.20-22, MAR50.1",
            source_module="phase5_k_full.py",
            input_source="previous phase outputs (phase2 SCVA, phase3 K_reduced, phase4 hedges)",
            df_input=merged,
            df_output=out,
            audit={"per_cp_scva_snh_hma": merged, "k_full_assembly": audit_df},
            reconciliation=recon,
            notes="rho/beta/DS/12.5 from config. K_full floored at beta*K_reduced.",
        )
    return out


if __name__ == "__main__":
    out = run_phase5()
    print(f"wrote {OUT_XLSX}\n")
    print(out.T.to_string())
