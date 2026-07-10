#!/usr/bin/env python3
"""
Fix medium-level reference links so "Source" points somewhere specific, not a
database homepage or nothing.

  * HMDB-derived biospecimen media  -> DOI 10.1093/nar/gkab1062 (HMDB 5.0 paper)
  * BMDB-derived biospecimen media  -> DOI 10.3390/metabo10060233 (BMDB paper)
  * any medium whose id/citation contains a PMCID and has no url -> the PMC article
  * any medium with a DOI but no url -> https://doi.org/<doi>

(Per-metabolite exact pages are handled in the UI, which now links each component's
HMDB/KEGG/ChEBI/SEED cross-reference to its own database page.)

Run:  python3 tools/curate_references.py [--dry]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")

HMDB_DOI = "10.1093/nar/gkab1062"
BMDB_DOI = "10.3390/metabo10060233"
PMC = re.compile(r"(PMC\d+)")


def curate(d):
    prov = d.setdefault("provenance", {})
    doi = prov.get("doi") or ""
    url = prov.get("url") or ""
    cit = prov.get("citation") or ""
    mid = d.get("id", "")
    changed = False
    # HMDB / BMDB biospecimen: attach the source paper DOI
    if not doi:
        if "hmdb" in mid or "HMDB" in cit:
            doi = HMDB_DOI; prov["doi"] = doi; changed = True
        elif "bmdb" in mid or "BMDB" in cit or "Bovine Metabolome" in cit:
            doi = BMDB_DOI; prov["doi"] = doi; changed = True
    # fill an empty/generic url
    generic = (url == "" or re.match(r"^https?://(www\.)?(hmdb\.ca|bovinedb\.ca|foodb\.ca)/?$", url))
    if generic:
        m = PMC.search(mid) or PMC.search(cit)
        if m:
            prov["url"] = "https://www.ncbi.nlm.nih.gov/pmc/articles/%s/" % m.group(1); changed = True
        elif doi:
            prov["url"] = "https://doi.org/" + doi; changed = True
    return changed


def main():
    dry = "--dry" in sys.argv
    changed = 0
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        if curate(d):
            changed += 1
            if not dry:
                with open(f, "w") as fh:
                    json.dump(d, fh, ensure_ascii=False)
    print("reference links curated:", changed)


if __name__ == "__main__":
    main()
