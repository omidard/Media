#!/usr/bin/env python3
"""
Honesty pass over literature-extracted media.

  * Every lit/complexlit/growthlit medium gets provenance.verification =
    "auto-extracted" so it is never presented as manually verified.
  * Media whose description/notes promise >=2 compound categories that are entirely
    absent from the components (a strong bad-extraction signal) are QUARANTINED:
    the file is removed and the id is logged to data/_quarantine.json.
  * Weaker warnings are recorded in provenance.formulation_warning for review.

Run:  python3 tools/flag_extractions.py [--dry]
"""
import os, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")
sys.path.insert(0, HERE)
from validate_formulations import check, LIT  # noqa: E402


def main():
    dry = "--dry" in sys.argv
    flagged = 0; quarantined = []
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        if not d["id"].startswith(LIT):
            continue
        prov = d.setdefault("provenance", {})
        prov["verification"] = "auto-extracted from primary literature; formulation not manually verified"
        w = check(d)
        strong = sum(1 for m in w if "promises" in m)
        if strong >= 2:
            quarantined.append({"id": d["id"], "name": d.get("name"), "reason": "; ".join(w)})
            if not dry:
                os.remove(f)
            continue
        if w:
            prov["formulation_warning"] = "; ".join(w)
            flagged += 1
        if not dry:
            with open(f, "w") as fh:
                json.dump(d, fh, ensure_ascii=False)
    if not dry:
        with open(os.path.join(REPO, "data", "_quarantine.json"), "w") as fh:
            json.dump(quarantined, fh, indent=1)
    print("lit media marked auto-extracted; with warnings:", flagged)
    print("quarantined (removed, demonstrably invalid):", len(quarantined))
    for q in quarantined:
        print("  -", q["id"], "::", q["reason"])


if __name__ == "__main__":
    main()
