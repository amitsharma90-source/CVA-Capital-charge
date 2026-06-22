"""Run the full BA-CVA pipeline: phases 1-5 (each emits its snapshot) + QA suite.

    /c/Users/amits/anaconda3/python.exe Model/run_all.py
"""
from __future__ import annotations

from phase1_inputs import run_phase1
from phase2_scva import run_phase2
from phase3_k_reduced import run_phase3
from phase4_hedges import run_phase4
from phase5_k_full import run_phase5
import qa_suite


def main() -> int:
    print("=== BA-CVA pipeline ===")
    run_phase1(write_snapshot=True)
    print("  phase1_inputs.xlsx     written")
    run_phase2(write_snapshot=True)
    print("  phase2_scva.xlsx       written")
    run_phase3(write_snapshot=True)
    print("  phase3_k_reduced.xlsx  written")
    run_phase4(write_snapshot=True)
    print("  phase4_hedges.xlsx     written")
    final = run_phase5(write_snapshot=True).iloc[0]
    print("  phase5_k_full.xlsx     written")
    print(f"\nFINAL: K_full={final['k_full']:.4f}  Capital={final['capital_full']:.4f}  RWA={final['rwa_full']:.4f}")
    print("\n=== QA suite ===")
    ok = qa_suite.run_all()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
