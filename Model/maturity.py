"""Effective maturity M_NS for BA-CVA netting sets (non-IMM).

Governing rule: CRE32.49 -- for derivatives subject to a master netting
agreement, M is the NOTIONAL-WEIGHTED AVERAGE of the transactions' maturities.
(Not the CRE32.47 cash-flow-weighted formula, which is for determined-cash-flow
instruments like loans/bonds.)

    M_NS = sum_i ( |Notional_i| * M_i ) / sum_i |Notional_i|

Per-product transaction maturity M_i (years from the valuation date):

    IRS / CommoditySwap / FXSwap / SFT : Trade_Maturity - valuation_date
        (FXSwap maturity includes the final notional re-exchange; periodic
         cashflows do NOT enter -- 32.49 is notional-weighted maturity)
    Swaption (physically settled)      : Underlying_End - valuation_date
        (time to final settlement of the underlying swap; CRE32.48 "maximum
         time to discharge the obligation")

Bounds (MAR50.15(2) + CRE32.46/32.51, all config-driven):
    * 5-year cap NOT applied (apply_five_year_cap = FALSE).
    * one-year floor (maturity_floor_years) applied by default;
    * if apply_cre32_51_carveout, qualifying short-term sets floor at one day.

Also provides the supervisory discount factor DF (MAR50.15 fn 3).
"""
from __future__ import annotations

import math
import datetime as dt
import pandas as pd

_DAYS_PER_YEAR = 365.25


def _to_date(v) -> dt.date | None:
    if v is None or (isinstance(v, float) and math.isnan(v)) or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def trade_maturity_years(row: pd.Series, val_date: dt.date) -> float:
    """M_i in years for one trade, per product convention above."""
    product = str(row["Product_Type"])
    if product == "Swaption":
        end = _to_date(row.get("Underlying_End"))
        if end is None:
            raise ValueError(f"Swaption {row.get('Trade_ID')} missing Underlying_End")
    else:
        end = _to_date(row.get("Trade_Maturity"))
        if end is None:
            raise ValueError(f"Trade {row.get('Trade_ID')} missing Trade_Maturity")
    return (end - val_date).days / _DAYS_PER_YEAR


def netting_set_maturity(trades: pd.DataFrame, val_date: dt.date, constants: dict) -> tuple[float, float, str]:
    """Return (M_NS, M_NS_raw, audit_text) for one netting set's trades.

    M_NS_raw is the pre-floor notional-weighted average; M_NS is after the
    floor/cap rules. The 5-year cap is applied only if config says so (FALSE here).
    """
    notionals = trades["Notional"].abs()
    mats = trades.apply(lambda r: trade_maturity_years(r, val_date), axis=1)
    total_notional = float(notionals.sum())
    if total_notional == 0:
        raise ValueError("netting set has zero total notional")
    m_raw = float((notionals * mats).sum() / total_notional)

    m = m_raw
    floor = float(constants["maturity_floor_years"])
    if bool(constants.get("apply_cre32_51_carveout", False)):
        floor = 1.0 / float(constants["business_days_per_year"])  # one-day floor (32.51)
    m = max(m, floor)
    if bool(constants.get("apply_five_year_cap", False)):
        m = min(m, 5.0)

    parts = ", ".join(
        f"{tid}:|{n:g}|x{mi:.4f}" for tid, n, mi in zip(trades["Trade_ID"], notionals, mats)
    )
    audit = (
        f"M_NS = Sigma(|N|*M_i)/Sigma|N| = [{parts}] / {total_notional:g} "
        f"= {m_raw:.4f}; floor={floor:.4f}, 5y_cap={'on' if constants.get('apply_five_year_cap') else 'off'} "
        f"=> M_NS={m:.4f}"
    )
    return m, m_raw, audit


def discount_factor(m: float, rate: float) -> float:
    """Supervisory DF = (1 - exp(-rate*M)) / (rate*M); ->1 as M->0 (MAR50.15 fn3)."""
    x = rate * m
    if x == 0:
        return 1.0
    return (1.0 - math.exp(-x)) / x


def discount_factor_audit(m: float, rate: float, df: float) -> str:
    return f"DF = (1 - e^(-{rate:g}*{m:.4f})) / ({rate:g}*{m:.4f}) = {df:.5f}"
