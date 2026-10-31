"""Run independent reference imports, then dependent selection and comparison.

Run from the infusion-audit folder:  python -m pipeline.run_all
"""
import sys

from . import build_compare, load_asp, load_reference, parse_hpt, select_drugs


def main() -> int:
    failures = []
    asp_ok = selection_ok = hospital_ok = False
    for name, step in (("load_asp", load_asp), ("load_reference", load_reference)):
        print(f"\n=== {name} ===", flush=True)
        try:
            ok = step.main() == 0
        except Exception as exc:
            ok = False
            print(f"FAILED {name}: {exc}")
        if not ok:
            failures.append(name)
        if name == "load_asp":
            asp_ok = ok

    if asp_ok:
        print("\n=== select_drugs ===", flush=True)
        try:
            selection_ok = select_drugs.main() == 0
        except Exception as exc:
            print(f"FAILED select_drugs: {exc}")
        if not selection_ok:
            failures.append("select_drugs")
    else:
        print("\nSKIPPED select_drugs: ASP reference build failed")
        failures.append("select_drugs (ASP dependency missing)")

    if selection_ok:
        print("\n=== parse_hpt ===", flush=True)
        try:
            hospital_ok = parse_hpt.main() == 0
        except Exception as exc:
            print(f"FAILED parse_hpt: {exc}")
        if not hospital_ok:
            failures.append("parse_hpt")
    else:
        print("\nSKIPPED parse_hpt: no validated CMS Part B drug scope; large MRF files remain catalogued, not processed")
        failures.append("parse_hpt (drug scope dependency missing)")

    if selection_ok and hospital_ok:
        print("\n=== build_compare ===", flush=True)
        try:
            if build_compare.main() != 0:
                failures.append("build_compare")
        except Exception as exc:
            print(f"FAILED build_compare: {exc}")
            failures.append("build_compare")
    else:
        print("\nSKIPPED build_compare: required current scope and hospital rows are not available")

    print("\n=== pipeline summary ===")
    print("Independent inputs processed: " + ("none failed" if not failures else ", ".join(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
