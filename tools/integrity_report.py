#!/usr/bin/env python3
"""Print a per-source integrity report: verification status, coverage, oxygen."""
import glob, json, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")


def source(i):
    for p, s in [("mediadive_", "DSMZ MediaDive"), ("usda_", "USDA"), ("food_", "FooDB"),
                 ("lit_", "Literature"), ("complexlit_", "Literature"), ("growthlit_", "Literature"),
                 ("biospecimen_", "Biospecimen")]:
        if i.startswith(p):
            return s
    return "other"


def main():
    by = collections.defaultdict(lambda: collections.Counter())
    ver = collections.Counter()
    tot = 0
    for f in glob.glob(os.path.join(MEDIA, "*.json")):
        d = json.load(open(f))
        tot += 1
        s = source(d["id"])
        by[s]["n"] += 1
        v = (d.get("provenance") or {}).get("verification", "")
        if v.startswith("paper-verified (corrected"):
            by[s]["corrected"] += 1; ver["corrected"] += 1
        elif v.startswith("paper-verified"):
            by[s]["confirmed"] += 1; ver["confirmed"] += 1
        elif v.startswith("auto-extracted"):
            by[s]["auto_unverified"] += 1; ver["auto_unverified"] += 1
        else:
            by[s]["curated_source"] += 1; ver["curated_source"] += 1
    print("=== MEDIA INTEGRITY REPORT ===  total media:", tot)
    print("%-16s %7s %10s %10s %12s %14s" % ("source", "n", "confirmed", "corrected", "unverified", "db-sourced"))
    for s in sorted(by, key=lambda x: -by[x]["n"]):
        c = by[s]
        print("%-16s %7d %10d %10d %12d %14d" % (
            s, c["n"], c["confirmed"], c["corrected"], c["auto_unverified"], c["curated_source"]))
    print("\ntotals:", dict(ver))
    q = os.path.join(REPO, "data", "_quarantine.json")
    if os.path.exists(q):
        print("quarantined (removed):", len(json.load(open(q))))


if __name__ == "__main__":
    main()
