"""Phase 1 -- Input normalization + M_NS/DF.

MAR50.15 fn 3 (DF); CRE32.49 (M_NS notional-weighted, non-IMM); MAR50.15(2)
(no 5y cap). One row per netting set out, carrying EAD_NS (given), computed
M_NS and computed DF_NS, ready for SCVA (Phase 2).
"""
from __future__ import annotations

import os
import datetime as dt
import pandas as pd

import config_loader as cfg
import maturity as mat
from phase_snapshot import write_phase_snapshot

ROOT = cfg.ROOT
INPUT_BOOK = os.path.join(ROOT, "Input", "CVA_CCR book.xlsx")
OUT_XLSX = os.path.join(ROOT, "Output", "phase1_inputs.xlsx")


def run_phase1(write_snapshot: bool = True) -> pd.DataFrame:
    constants = cfg.load_constants()
    rate = float(constants["discount_rate"])
    val_date = dt.date.fromisoformat(str(constants["valuation_date"])[:10])

    ns = pd.read_excel(INPUT_BOOK, sheet_name="Netting_Sets")
    trades = pd.read_excel(INPUT_BOOK, sheet_name="Covered_Transactions")

    rows, audit_rows = [], []
    for _, nsrow in ns.iterrows():
        ns_id = nsrow["NS#"]
        ns_trades = trades[trades["NS#"] == ns_id].reset_index(drop=True)
        if ns_trades.empty:
            raise ValueError(f"netting set {ns_id} has no covered transactions")
        m_ns, m_raw, m_audit = mat.netting_set_maturity(ns_trades, val_date, constants)
        df_ns = mat.discount_factor(m_ns, rate)
        df_audit = mat.discount_factor_audit(m_ns, rate, df_ns)

        rows.append({
            "NS#": ns_id,
            "Counterparty": nsrow["Counterparty"],
            "Sector": nsrow["Sector"],
            "Credit_Quality": nsrow["Credit_Quality"],
            "Region": nsrow["Region"],
            "EAD_NS": float(nsrow["EAD_NS"]),
            "M_NS": m_ns,
            "DF_NS": df_ns,
        })
        audit_rows.append({"NS#": ns_id, "M_NS_calc": m_audit, "DF_NS_calc": df_audit})

    out = pd.DataFrame(rows)
    audit_df = pd.DataFrame(audit_rows)

    recon = pd.DataFrame({
        "item": [
            "DF_in_0_1_all", "M_NS_positive_all", "five_year_cap_applied",
            "n_counterparties", "EAD_total",
        ],
        "value": [
            bool((out["DF_NS"] > 0).all() and (out["DF_NS"] <= 1).all()),
            bool((out["M_NS"] > 0).all()),
            bool(constants.get("apply_five_year_cap", False)),
            int(out["Counterparty"].nunique()),
            float(out["EAD_NS"].sum()),
        ],
    })

    if write_snapshot:
        os.makedirs(os.path.dirname(OUT_XLSX), exist_ok=True)
        write_phase_snapshot(
            OUT_XLSX,
            phase_number=1,
            phase_name="Input normalization + M_NS/DF",
            mar_clause="MAR50.15 fn3; CRE32.49; MAR50.15(2)",
            source_module="phase1_inputs.py + maturity.py",
            input_source="Input/CVA_CCR book.xlsx (Netting_Sets, Covered_Transactions)",
            df_input=ns,
            df_output=out,
            audit={"covered_transactions": trades, "M_NS_and_DF_per_NS": audit_df},
            reconciliation=recon,
            notes="M_NS per CRE32.49 notional-weighted; 5y cap off; 1y floor (config).",
        )
    return out


if __name__ == "__main__":
    out = run_phase1()
    print(f"wrote {OUT_XLSX}\n")
    print(out.to_string(index=False))
