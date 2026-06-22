"""Phase 2 -- SCVA per counterparty.

MAR50.15-16:  SCVA_c = (1/alpha) * RW_c * Sigma_NS ( M_NS * EAD_NS * DF_NS ).
RW_c from MAR50.16 Table 1 by counterparty sector x credit quality.
Consumes Phase 1's per-netting-set output.
"""
from __future__ import annotations

import os
import pandas as pd

import config_loader as cfg
from phase_snapshot import write_phase_snapshot
from phase1_inputs import run_phase1

ROOT = cfg.ROOT
OUT_XLSX = os.path.join(ROOT, "Output", "phase2_scva.xlsx")


def run_phase2(write_snapshot: bool = True, phase1_out: pd.DataFrame | None = None) -> pd.DataFrame:
    constants = cfg.load_constants()
    alpha = float(constants["alpha"])
    rw_table = cfg.load_rw_table()

    ns = run_phase1(write_snapshot=False) if phase1_out is None else phase1_out.copy()

    # per-netting-set maturity-discount-weighted EAD (M*EAD*DF)
    ns = ns.copy()
    ns["mat_disc_weighted_ead"] = ns["M_NS"] * ns["EAD_NS"] * ns["DF_NS"]

    rows, audit_rows = [], []
    for cp, grp in ns.groupby("Counterparty", sort=False):
        sectors = grp["Sector"].unique()
        quals = grp["Credit_Quality"].unique()
        if len(sectors) != 1 or len(quals) != 1:
            raise ValueError(f"counterparty {cp} has inconsistent sector/quality across netting sets")
        rw_c = cfg.rw_lookup(rw_table, sectors[0], quals[0])
        sum_mdw = float(grp["mat_disc_weighted_ead"].sum())
        scva = (1.0 / alpha) * rw_c * sum_mdw

        rows.append({
            "Counterparty": cp,
            "Sector": sectors[0],
            "Credit_Quality": quals[0],
            "RW_c": rw_c,
            "n_netting_sets": int(len(grp)),
            "sum_mat_disc_weighted_ead": sum_mdw,
            "scva_per_cp": scva,
        })
        terms = " + ".join(
            f"{r['NS#']}:{r['M_NS']:.4f}x{r['EAD_NS']:g}x{r['DF_NS']:.5f}"
            for _, r in grp.iterrows()
        )
        audit_rows.append({
            "Counterparty": cp,
            "SCVA_calc": (
                f"SCVA = (1/{alpha:g})*{rw_c:g}*Sigma_NS(M*EAD*DF) "
                f"= (1/{alpha:g})*{rw_c:g}*[{terms}] "
                f"= (1/{alpha:g})*{rw_c:g}*{sum_mdw:.4f} = {scva:.4f}"
            ),
        })

    out = pd.DataFrame(rows)
    audit_df = pd.DataFrame(audit_rows)

    recon = pd.DataFrame({
        "item": ["scva_nonnegative_all", "n_counterparties", "scva_total"],
        "value": [bool((out["scva_per_cp"] >= 0).all()), int(len(out)), float(out["scva_per_cp"].sum())],
    })

    if write_snapshot:
        os.makedirs(os.path.dirname(OUT_XLSX), exist_ok=True)
        write_phase_snapshot(
            OUT_XLSX,
            phase_number=2,
            phase_name="SCVA per counterparty",
            mar_clause="MAR50.15-16",
            source_module="phase2_scva.py",
            input_source="previous phase output (phase1_inputs.py)",
            df_input=ns,
            df_output=out,
            audit={"per_netting_set_mat_disc_weighted_ead": ns, "SCVA_per_cp": audit_df},
            reconciliation=recon,
            notes="RW_c from MAR50.16; alpha from config.",
        )
    return out


if __name__ == "__main__":
    out = run_phase2()
    print(f"wrote {OUT_XLSX}\n")
    print(out.to_string(index=False))
