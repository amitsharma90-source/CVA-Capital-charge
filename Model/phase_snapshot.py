"""Shared phase-snapshot writer for the BA-CVA engine.

One Excel per phase, five fixed sheets, identical contract for every phase
(project rule). Built generic; no FRTB code imported.

Sheets
------
00_manifest        phase metadata + row/column counts + timestamp + notes
10_input           the frame the phase received  (= phase N-1's 20_output)
20_output          the frame the phase produced  (= phase N+1's 10_input)
30_audit           per-row calculation chronology / drill-downs (text)
40_reconciliation  rows_in, rows_out, and >=1 conservation/sanity invariant

The five sheets above are fixed and mandatory for every phase. In addition, a
phase MAY emit optional APPENDIX sheets via `appendix_sheets=` -- numbered 50+
(e.g. `50_index_calc`) so they sort after the fixed five. This is a uniform,
sanctioned extension available to ALL phases (not a per-phase exception): the
fixed five keep the re-runnability contract (phase N's 10_input == phase N-1's
20_output is unaffected by appendices), while appendices carry heavy supporting
working that would otherwise bloat 30_audit.

Use `write_phase_snapshot(...)` from every phase module. Do not invent ad-hoc
snapshot layouts.
"""
from __future__ import annotations

import datetime as _dt
from typing import Mapping, Sequence

import pandas as pd


def _stack_named_frames(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack a dict of DataFrames into one sheet with a header row per section."""
    blocks: list[pd.DataFrame] = []
    for title, df in frames.items():
        header = pd.DataFrame({"section": [f"### {title} ###"]})
        blocks.append(header)
        blocks.append(df.reset_index(drop=True))
        blocks.append(pd.DataFrame({"section": [""]}))  # spacer
    if not blocks:
        return pd.DataFrame()
    return pd.concat(blocks, ignore_index=True)


def _as_frame(obj) -> pd.DataFrame:
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, Mapping):
        # mapping of label -> scalar  OR  label -> DataFrame
        if all(isinstance(v, pd.DataFrame) for v in obj.values()):
            return _stack_named_frames(obj)
        return pd.DataFrame({"item": list(obj.keys()), "value": list(obj.values())})
    if isinstance(obj, Sequence):
        return pd.DataFrame(obj)
    raise TypeError(f"cannot coerce {type(obj)} to a sheet frame")


def write_phase_snapshot(
    path: str,
    *,
    phase_number: int,
    phase_name: str,
    mar_clause: str,
    source_module: str,
    input_source: str,
    df_input: pd.DataFrame,
    df_output: pd.DataFrame,
    audit,
    reconciliation,
    notes: str = "",
    appendix_sheets: Mapping[str, object] | None = None,
) -> str:
    """Write one phase workbook with the five fixed sheets.

    Parameters
    ----------
    path           : output .xlsx path
    phase_number   : 1..5
    phase_name     : <=5-word phase name
    mar_clause     : governing MAR50 / CRE clause(s)
    source_module  : the .py module that produced this phase
    input_source   : input file(s) or "previous phase output"
    df_input       : frame received by the phase  -> 10_input
    df_output      : frame produced by the phase  -> 20_output
    audit          : DataFrame, or dict{label->DataFrame}, or dict{label->scalar}
    reconciliation : DataFrame, or dict{label->value}; rows_in/rows_out are added
    notes          : free-form manifest notes
    appendix_sheets: optional {sheet_name: DataFrame | dict[str,DataFrame]}; names
                     should be numbered 50+ (e.g. "50_index_calc") to sort after
                     the fixed five. Available uniformly to every phase.
    """
    _FIXED = {"00_manifest", "10_input", "20_output", "30_audit", "40_reconciliation"}
    for nm in (appendix_sheets or {}):
        if nm in _FIXED:
            raise ValueError(f"appendix sheet '{nm}' collides with a fixed sheet name")
    df_input = df_input if df_input is not None else pd.DataFrame()
    df_output = df_output if df_output is not None else pd.DataFrame()

    manifest = pd.DataFrame(
        {
            "field": [
                "phase_number", "phase_name", "mar_clause", "source_module",
                "input_source", "rows_in", "rows_out", "columns_in",
                "columns_out", "run_timestamp", "notes",
            ],
            "value": [
                phase_number, phase_name, mar_clause, source_module,
                input_source, len(df_input), len(df_output),
                df_input.shape[1], df_output.shape[1],
                _dt.datetime.now().isoformat(timespec="seconds"), notes,
            ],
        }
    )

    audit_df = _as_frame(audit)

    # reconciliation always carries rows_in / rows_out up front
    recon_df = _as_frame(reconciliation)
    base = pd.DataFrame({"item": ["rows_in", "rows_out"], "value": [len(df_input), len(df_output)]})
    if not recon_df.empty and set(recon_df.columns) >= {"item", "value"}:
        recon_df = pd.concat([base, recon_df], ignore_index=True)
    elif recon_df.empty:
        recon_df = base
    # if recon_df has a different schema, leave it but prepend base as its own block
    elif set(recon_df.columns) != {"item", "value"}:
        recon_df = pd.concat([base, recon_df], ignore_index=True)

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        manifest.to_excel(xl, sheet_name="00_manifest", index=False)
        df_input.to_excel(xl, sheet_name="10_input", index=False)
        df_output.to_excel(xl, sheet_name="20_output", index=False)
        audit_df.to_excel(xl, sheet_name="30_audit", index=False)
        recon_df.to_excel(xl, sheet_name="40_reconciliation", index=False)
        for nm, content in (appendix_sheets or {}).items():
            _as_frame(content).to_excel(xl, sheet_name=nm, index=False)
    return path
