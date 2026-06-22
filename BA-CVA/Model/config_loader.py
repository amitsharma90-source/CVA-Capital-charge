"""Runtime reader for Input/BA_CVA_Config.xlsx.

Every engine module gets its regulatory constants and tables from here, so no
constant is hardcoded in calculation code. Flags stored as 0/1 in the mixed
`value` column are cast back to bool.
"""
from __future__ import annotations

import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "Input", "BA_CVA_Config.xlsx")

_FLAG_NAMES = {"apply_five_year_cap", "apply_cre32_51_carveout"}


def load_constants(path: str = CONFIG_PATH) -> dict:
    """Return {name: value}; flags cast to bool, numerics to float, dates as str."""
    df = pd.read_excel(path, sheet_name="Constants")
    out: dict = {}
    for _, row in df.iterrows():
        name, val = row["name"], row["value"]
        if name in _FLAG_NAMES:
            out[name] = bool(float(val)) if not isinstance(val, bool) else val
        else:
            out[name] = val
    return out


def load_rw_table(path: str = CONFIG_PATH) -> pd.DataFrame:
    """MAR50.16 Table 1, indexed by sector_code, columns RW_IG / RW_HY_NR."""
    return pd.read_excel(path, sheet_name="RW_Table").set_index("sector_code")


def load_rhc_table(path: str = CONFIG_PATH) -> dict:
    """MAR50.26 Table 2: {relationship: r_hc}."""
    df = pd.read_excel(path, sheet_name="r_hc_Table")
    return dict(zip(df["relationship"], df["r_hc"]))


def load_index_constituents(book_path: str) -> pd.DataFrame:
    """Index_Constituents sheet from the input book; empty frame if absent."""
    try:
        return pd.read_excel(book_path, sheet_name="Index_Constituents")
    except (ValueError, FileNotFoundError):
        return pd.DataFrame()


def rw_lookup(rw_table: pd.DataFrame, sector_code: str, credit_quality: str) -> float:
    """Risk weight (decimal) for a sector x {IG, HY/NR}. NR maps to HY/NR column."""
    if sector_code not in rw_table.index:
        raise KeyError(f"sector_code '{sector_code}' not in RW_Table (MAR50.16)")
    col = "RW_IG" if str(credit_quality).upper() == "IG" else "RW_HY_NR"
    return float(rw_table.loc[sector_code, col])
