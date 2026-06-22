"""Phase 4 -- Hedge recognition: SNH_c, IH, HMA_c.

MAR50.23  SNH_c = Sigma_h ( r_hc * M_h * B_h * DF_h * RW_h )
MAR50.24  IH    = Sigma_i ( M_i * B_i * DF_i * RW_i ),  RW_i = RW_base * 0.7
MAR50.25  HMA_c = Sigma_h ( 1 - r_hc^2 ) * ( RW_h * M_h * B_h * DF_h )^2
MAR50.26  r_hc resolved against Hedged_Counterparty: direct 100 / legal 80 / sector-region 50.

Returns per-counterparty (SNH_c, HMA_c) for ALL counterparties (0 if unhedged)
plus the single scalar IH.
"""
from __future__ import annotations

import os
import datetime as dt
import pandas as pd

import config_loader as cfg
import maturity as mat
from phase_snapshot import write_phase_snapshot
from phase1_inputs import run_phase1

ROOT = cfg.ROOT
INPUT_BOOK = os.path.join(ROOT, "Input", "CVA_CCR book.xlsx")
OUT_XLSX = os.path.join(ROOT, "Output", "phase4_hedges.xlsx")


def _resolve_rhc(hedge: pd.Series, cp_sector: str, cp_region: str, rhc: dict) -> tuple[float, str]:
    """First-match resolution against Hedged_Counterparty (MAR50.26). No edge cases."""
    hc = hedge["Hedged_Counterparty"]
    if hedge["Reference_Counterparty"] == hc:
        return rhc["direct"], "direct"
    legal = hedge.get("Legal_Reference")
    if pd.notna(legal) and str(legal) != "" and legal == hc:
        return rhc["legal"], "legal"
    if hedge["Sector"] == cp_sector and hedge["Region"] == cp_region:
        return rhc["sector_region"], "sector_region"
    raise ValueError(f"hedge {hedge.get('Hedge_ID')} resolves to no r_hc tier (edge case not allowed)")


def _index_base_rw(name, constituents: pd.DataFrame, rw_table, fallback) -> tuple[float, str, int]:
    """MAR50.24(4)(b) name-weighted-average RW from constituents; else given fallback.

    Equal weights => simple average of constituents' MAR50.16 sector RWs.
    """
    if not constituents.empty:
        cons = constituents[constituents["Index_Name"] == name]
        if not cons.empty:
            w = cons["Weight"].astype(float)
            rws = cons.apply(
                lambda c: cfg.rw_lookup(rw_table, c["MAR50_Sector"], c["Credit_Quality"]), axis=1)
            return float((w * rws).sum() / w.sum()), "name-wtd avg (constituents)", int(len(cons))
    return float(fallback), "given (RW_index_base)", 0


def run_phase4(write_snapshot: bool = True, phase1_out: pd.DataFrame | None = None):
    constants = cfg.load_constants()
    rate = float(constants["discount_rate"])
    idx_mult = float(constants["index_diversification_mult"])
    val_date = dt.date.fromisoformat(str(constants["valuation_date"])[:10])
    rw_table = cfg.load_rw_table()
    rhc = cfg.load_rhc_table()

    ns = run_phase1(write_snapshot=False) if phase1_out is None else phase1_out.copy()
    # counterparty -> (sector, region) for sector-region matching
    cp_static = ns.drop_duplicates("Counterparty").set_index("Counterparty")[["Sector", "Region"]]
    all_cps = ns["Counterparty"].drop_duplicates().tolist()

    sn = pd.read_excel(INPUT_BOOK, sheet_name="SingleName_Hedges")
    idx = pd.read_excel(INPUT_BOOK, sheet_name="Index_Hedges")

    # --- single-name hedges -> per-hedge SNH / HMA contributions ---
    sn_detail = []
    for _, h in sn.iterrows():
        hc = h["Hedged_Counterparty"]
        if hc not in cp_static.index:
            raise ValueError(f"hedge {h['Hedge_ID']} hedges unknown counterparty {hc}")
        cp_sector, cp_region = cp_static.loc[hc, "Sector"], cp_static.loc[hc, "Region"]
        r_hc, tier = _resolve_rhc(h, cp_sector, cp_region, rhc)
        m_h = (dt.date.fromisoformat(str(h["Maturity"])[:10]) - val_date).days / 365.25
        df_h = mat.discount_factor(m_h, rate)
        rw_h = cfg.rw_lookup(rw_table, h["Sector"], h["Ref_Credit_Quality"])
        b_h = float(h["Notional"])
        base = rw_h * m_h * b_h * df_h               # RW_h * M_h * B_h * DF_h
        snh_contrib = r_hc * base                     # 50.23
        hma_contrib = (1.0 - r_hc ** 2) * base ** 2   # 50.25
        sn_detail.append({
            "Hedge_ID": h["Hedge_ID"], "Hedged_Counterparty": hc,
            "Reference_Counterparty": h["Reference_Counterparty"], "tier": tier,
            "r_hc": r_hc, "M_h": m_h, "B_h": b_h, "DF_h": df_h, "RW_h": rw_h,
            "rw_m_b_df": base, "snh_contrib": snh_contrib, "hma_contrib": hma_contrib,
            "Protection_Seller": h.get("Protection_Seller", ""),
            "Cleared_QCCP": bool(h.get("Cleared_QCCP", False)),
        })
    sn_detail = pd.DataFrame(sn_detail)

    # --- index hedges -> single IH scalar ---
    constituents = cfg.load_index_constituents(INPUT_BOOK)
    idx_detail = []
    ih_total = 0.0
    for _, ix in idx.iterrows():
        name = ix["Index_Name"]
        rw_base, rw_src, n_cons = _index_base_rw(name, constituents, rw_table, ix["RW_index_base"])
        m_i = (dt.date.fromisoformat(str(ix["Maturity"])[:10]) - val_date).days / 365.25
        df_i = mat.discount_factor(m_i, rate)
        rw_i = rw_base * idx_mult                       # 50.24(4) x0.7
        b_i = float(ix["Notional"])
        ih_contrib = m_i * b_i * df_i * rw_i            # 50.24
        ih_total += ih_contrib
        idx_detail.append({
            "Index_ID": ix["Index_ID"], "Index_Name": name, "M_i": m_i, "B_i": b_i,
            "DF_i": df_i, "rw_base": rw_base, "rw_base_source": rw_src,
            "n_constituents": n_cons, "RW_i": rw_i, "ih_contrib": ih_contrib,
            "Cleared_QCCP": bool(ix.get("Cleared_QCCP", True)),
        })
    idx_detail = pd.DataFrame(idx_detail)

    # --- aggregate to per-counterparty SNH_c / HMA_c (all CPs, 0 if unhedged) ---
    rows = []
    for cp in all_cps:
        hsel = sn_detail[sn_detail["Hedged_Counterparty"] == cp] if not sn_detail.empty else sn_detail
        rows.append({
            "Counterparty": cp,
            "snh_per_cp": float(hsel["snh_contrib"].sum()) if not hsel.empty else 0.0,
            "hma_per_cp": float(hsel["hma_contrib"].sum()) if not hsel.empty else 0.0,
        })
    out = pd.DataFrame(rows)

    # audit
    audit_sn = pd.DataFrame([{
        "Hedge_ID": r["Hedge_ID"],
        "snh_calc": (f"{r['tier']}: SNH += r_hc*M*B*DF*RW = {r['r_hc']:g}*{r['M_h']:.4f}*{r['B_h']:g}"
                     f"*{r['DF_h']:.5f}*{r['RW_h']:g} = {r['snh_contrib']:.4f}"),
        "hma_calc": (f"HMA += (1-{r['r_hc']:g}^2)*({r['RW_h']:g}*{r['M_h']:.4f}*{r['B_h']:g}*{r['DF_h']:.5f})^2 "
                     f"= {1-r['r_hc']**2:g}*{r['rw_m_b_df']:.4f}^2 = {r['hma_contrib']:.4f}"),
    } for _, r in sn_detail.iterrows()]) if not sn_detail.empty else pd.DataFrame()

    direct_hma = sn_detail.loc[sn_detail["tier"] == "direct", "hma_contrib"] if not sn_detail.empty else pd.Series(dtype=float)
    recon = pd.DataFrame({
        "item": ["IH_total", "direct_hedge_HMA_zero", "snh_total", "hma_total", "n_single_name_hedges"],
        "value": [
            ih_total,
            bool((direct_hma.abs() < 1e-12).all()) if len(direct_hma) else True,
            float(out["snh_per_cp"].sum()), float(out["hma_per_cp"].sum()), int(len(sn_detail)),
        ],
    })

    # --- appendix sheet 50_index_calc: dedicated index-hedge working ---
    appendix = None
    if not constituents.empty and not idx_detail.empty:
        cons = constituents.copy()
        cons["RW"] = cons.apply(
            lambda c: cfg.rw_lookup(rw_table, c["MAR50_Sector"], c["Credit_Quality"]), axis=1)
        cons["contribution"] = cons["Weight"] * cons["RW"]
        # per-index sector build-up (IG and HY use different RW columns, so group by index)
        sector_summary = (cons.groupby(["Index_Name", "MAR50_Sector"])
                          .agg(n_names=("RW", "size"), RW=("RW", "first"),
                               weight_share=("Weight", "sum"), contribution=("contribution", "sum"))
                          .reset_index().sort_values(["Index_Name", "contribution"], ascending=[True, False]))
        totals = (cons.groupby("Index_Name")
                  .agg(n_names=("RW", "size"), weight_share=("Weight", "sum"),
                       contribution=("contribution", "sum")).reset_index())
        totals["MAR50_Sector"] = "TOTAL = rw_base"
        totals["RW"] = None
        sector_summary = pd.concat([sector_summary, totals], ignore_index=True).sort_values(
            ["Index_Name", "contribution"], ascending=[True, False])
        appendix = {
            "50_index_sector_summary": sector_summary,                       # per-index rw_base build-up
            "51_index_ih_buildup": idx_detail,                               # RW_i = rw_base*0.7; IH = M*B*DF*RW_i
            "52_index_constituents": cons[[                                  # IG 125 + HY 100, Option B sectors
                "Index_Name", "No", "Reference_Entity", "Sub_Index",
                "MAR50_Sector", "Credit_Quality", "Weight", "RW"]],
        }

    if write_snapshot:
        os.makedirs(os.path.dirname(OUT_XLSX), exist_ok=True)
        write_phase_snapshot(
            OUT_XLSX,
            phase_number=4,
            phase_name="Hedge recognition SNH/IH/HMA",
            mar_clause="MAR50.23-26",
            source_module="phase4_hedges.py",
            input_source="Input/CVA_CCR book.xlsx (SingleName_Hedges, Index_Hedges) + phase1",
            df_input=sn,
            df_output=out,
            audit={"single_name_detail": sn_detail, "index_detail": idx_detail, "calc": audit_sn},
            reconciliation=recon,
            notes=f"IH (single scalar) = {ih_total:.6f}. Direct hedge => HMA=0 (50.25). "
                  f"Index RW build-up in appendix sheets 50/51/52.",
            appendix_sheets=appendix,
        )
    return out, ih_total, sn_detail, idx_detail


if __name__ == "__main__":
    out, ih, sn_detail, idx_detail = run_phase4()
    print(f"wrote {OUT_XLSX}\n")
    print("per-counterparty SNH/HMA:")
    print(out.to_string(index=False))
    print(f"\nIH (index hedge scalar) = {ih:.6f}")
    print("\nsingle-name hedge detail:")
    print(sn_detail[["Hedge_ID", "Hedged_Counterparty", "tier", "r_hc", "M_h", "DF_h", "RW_h", "snh_contrib", "hma_contrib"]].to_string(index=False))
