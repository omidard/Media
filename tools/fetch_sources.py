#!/usr/bin/env python3
"""
fetch_sources — re-acquire the raw upstream inputs that were lost with the deleted
scratchpad (finding PIPE-01), and record honestly what could not be re-acquired.

    python3 tools/fetch_sources.py --list
    python3 tools/fetch_sources.py bigg metanetx
    python3 tools/fetch_sources.py mediadive --limit 25       # bounded sample
    python3 tools/fetch_sources.py mediadive --full           # all ~3,200 media
    python3 tools/fetch_sources.py --all
    python3 tools/fetch_sources.py --fixtures                 # write tests/fixtures/

Everything lands under $MEDIA_SOURCES (default data/_sources/), which is gitignored:
the payloads are large and some are licence-encumbered. What IS committed is
data/_sources/MANIFEST.json — the provenance ledger recording, per source: the URL,
the HTTP status actually observed, the retrieval date, the byte count, the sha256,
the licence, and whether the source is recoverable at all.

Sources that CANNOT be re-acquired are listed too, with status "lost" and the reason.
That is the point: an absent input is recorded as absent, never implied to exist.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mediapaths import REPO, SOURCES  # noqa: E402

UA = "MediaDB-source-recovery/1.0 (+https://omidard.github.io/Media)"
MANIFEST = os.path.join(SOURCES, "MANIFEST.json")

SOURCES_SPEC = {
    "bigg": {
        "licence": "BiGG Models: free for academic use; see http://bigg.ucsd.edu/license",
        "why": "bigg_models_metabolites.txt is the input to build_bigg_dict.py, which "
               "generates the mapping backbone tools/bigg_metabolite_dict.json; "
               "bigg_models_reactions.txt is the input to build_bigg_exchange_ids.py, "
               "which decides whether an EX_ id names a reaction BiGG actually has",
        "files": [("bigg_models_metabolites.txt",
                   "http://bigg.ucsd.edu/static/namespace/bigg_models_metabolites.txt"),
                  ("bigg_models_reactions.txt",
                   "http://bigg.ucsd.edu/static/namespace/bigg_models_reactions.txt")],
    },
    "metanetx": {
        "licence": "CC BY 4.0 (MetaNetX)",
        "why": "chem_xref.tsv / chem_prop.tsv feed build_xref.py, which adds the "
               "cross-references every mapping claim should be verifiable against",
        "files": [("chem_xref.tsv", "https://www.metanetx.org/cgi-bin/mnxget/mnxref/chem_xref.tsv"),
                  ("chem_prop.tsv", "https://www.metanetx.org/cgi-bin/mnxget/mnxref/chem_prop.tsv")],
    },
    "usda": {
        "licence": "US Government public domain (17 U.S.C. 105), USDA FoodData Central",
        "why": "7,424 usda_ media (54.9% of the corpus) are built from these zips",
        "files": [("ff.zip",
                   "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_json_2024-04-18.zip"),
                  ("sr_legacy.zip",
                   "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_json_2018-04.zip")],
    },
    "mediadive": {
        "licence": "CC BY 4.0 (DSMZ MediaDive): attribution and licence notice required "
                   "by CC BY 3(a)(1)(C); currently under-attributed in the shipped records",
        "why": "3,148 mediadive_ media (23.3%); the REST API is public and the repo's own "
               "tools/mediadive/fetch_media.py already targets it",
        "rest": "https://mediadive.dsmz.de/rest",
    },
    "mediadb": {
        "licence": "All Rights Reserved (MediaDB, Institute for Systems Biology): "
                   "redistribution is segregated and labelled, not relicensed",
        "why": "471 mdb_ media; tools/mediadb/fetch_mediadb.py scrapes the public pages",
        "scrape": "https://mediadb.systemsbiology.net/defined_media",
    },
    "foodb": {
        "licence": "CC BY-NC 4.0 (FooDB): non-commercial",
        "why": "701 food_ media are built from the FooDB CSV dump",
        # NB the release slug is 2020_4_7, not 2020_04_07 (the unpacked directory the
        # builders read is foodb_2020_04_07_csv); the padded form 404s.
        "files": [("foodb_csv.tar.gz", "https://foodb.ca/public/system/downloads/foodb_2020_4_7_csv.tar.gz")],
        "manual": "FooDB's download URL changes between releases and the host often "
                  "requires a browser session. If the fetch fails, download the CSV "
                  "dump by hand from https://foodb.ca/downloads and unpack it to "
                  "$MEDIA_SOURCES/foodb/foodb_2020_04_07_csv/.",
    },
    "hmdb": {
        "licence": "CC BY-NC 4.0 (HMDB): non-commercial; terms must be accepted",
        "why": "the 7 biospecimen_hmdb_ media",
        "manual": "HMDB requires accepting its terms before download. Fetch "
                  "hmdb_metabolites.zip by hand from https://hmdb.ca/downloads and put "
                  "it at $MEDIA_SOURCES/hmdb/hmdb_metabolites.zip.",
    },
    "bmdb": {
        "licence": "Bovine Metabolome Database — see https://bovinedb.ca",
        "why": "the biospecimen_bmdb_ media (bovine rumen, colostrum, ...)",
        "manual": "Download the BMDB metabolite export by hand to "
                  "$MEDIA_SOURCES/bmdb/bmdb_metabolites.zip.",
    },
    # ---- not recoverable ----------------------------------------------------
    "lit": {
        "status": "lost",
        "licence": "n/a",
        "why": "1,456 media (lit_ 87 + growthlit_ 1,036 + complexlit_ 333)",
        "lost_reason":
            "the compositions were extracted by an LLM agent (tools/lit/lit_mining.js) "
            "into batch_*.json files that were deleted with the scratchpad. Re-running "
            "the miner produces DIFFERENT extractions that would be filed under the SAME "
            "PMCIDs, DOIs and 'verbatim proving snippet' fields — new content wearing the "
            "old citations. These records are a frozen expert-curated snapshot.",
    },
    "growthdb": {
        "status": "lost",
        "licence": "n/a",
        "why": "the GrowthDB -> Media handoffs (media_to_add.json, media_backmap.json)",
        "lost_reason":
            "both handoff files lived in a second deleted scratchpad, and "
            "tools/add_formulated_growthdb.py consumed its own input (it pops "
            "medium.exchanges from growth_records.json). Measured today: 0 records are "
            "still eligible, so re-running it creates zero media.",
    },
}


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get(url: str, timeout: int = 120) -> tuple[int, bytes | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, None, str(e)
    except Exception as e:                                  # noqa: BLE001 - recorded
        return 0, None, "%s: %s" % (type(e).__name__, e)


def download(name: str, fname: str, url: str) -> dict:
    d = os.path.join(SOURCES, name)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, fname)
    t0 = time.time()
    status, body, err = _get(url)
    rec = {"file": os.path.relpath(dest, REPO), "url": url, "http_status": status,
           "retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "seconds": round(time.time() - t0, 1)}
    if status == 200 and body:
        with open(dest, "wb") as fh:
            fh.write(body)
        rec |= {"ok": True, "bytes": len(body), "sha256": sha256_file(dest)}
        print("  OK   %-28s %8.1f MB  %s" % (fname, len(body) / 1e6, url))
    else:
        rec |= {"ok": False, "error": err or "HTTP %s" % status}
        print("  FAIL %-28s HTTP %s  %s" % (fname, status, err[:120]))
    return rec


def fetch_mediadive(limit: int | None, full: bool) -> list[dict]:
    """MediaDive REST: the medium list, the ingredient list, and per-medium details."""
    base = SOURCES_SPEC["mediadive"]["rest"]
    d = os.path.join(SOURCES, "mediadive")
    os.makedirs(os.path.join(d, "details"), exist_ok=True)
    out = []
    for fname, path in (("mdive.json", "/media"), ("ingredients.json", "/ingredients")):
        out.append(download("mediadive", fname, base + path))
    listing = os.path.join(d, "mdive.json")
    if not os.path.exists(listing):
        print("  medium list unavailable; skipping details")
        return out
    with open(listing, encoding="utf-8") as fh:
        ids = [str(x["id"]) for x in (json.load(fh).get("data") or [])]
    todo = ids if full else ids[:(limit or 25)]
    print("  details: fetching %d of %d media%s"
          % (len(todo), len(ids), "" if full else "  (use --full for all)"))
    ok = fail = 0
    for i, mid in enumerate(todo, 1):
        dest = os.path.join(d, "details", "%s.json" % mid)
        if os.path.exists(dest):
            ok += 1
            continue
        status, body, err = _get("%s/medium/%s" % (base, mid), timeout=60)
        if status == 200 and body:
            with open(dest, "wb") as fh:
                fh.write(body)
            ok += 1
        else:
            fail += 1
        if i % 100 == 0:
            print("    %d/%d (ok %d, fail %d)" % (i, len(todo), ok, fail))
        time.sleep(0.05)                     # be a polite client
    out.append({"file": "data/_sources/mediadive/details", "url": base + "/medium/{id}",
                "http_status": 200 if ok else 0, "ok": bool(ok),
                "n_details_fetched": ok, "n_details_failed": fail,
                "n_media_upstream": len(ids), "complete": bool(full and not fail),
                "retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    print("  details fetched: %d ok, %d failed" % (ok, fail))
    return out


def load_manifest() -> dict:
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as fh:
            return json.load(fh)
    return {"schema": "mediadb-source-manifest/1", "sources": {}}


def save_manifest(man: dict) -> None:
    os.makedirs(SOURCES, exist_ok=True)
    man["updated_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=1)
    print("\nsource manifest -> %s" % os.path.relpath(MANIFEST, REPO))


def run(names, limit, full) -> int:
    man = load_manifest()
    for name in names:
        spec = SOURCES_SPEC[name]
        entry = {k: spec[k] for k in ("licence", "why") if k in spec}
        print("\n== %s" % name)
        if spec.get("status") == "lost":
            entry |= {"status": "lost", "lost_reason": spec["lost_reason"], "artifacts": []}
            print("  PERMANENTLY LOST — %s" % spec["lost_reason"][:160])
        elif "files" in spec:
            arts = [download(name, f, u) for f, u in spec["files"]]
            entry |= {"status": "recovered" if all(a["ok"] for a in arts)
                      else ("partial" if any(a["ok"] for a in arts) else "unavailable"),
                      "artifacts": arts}
            if spec.get("manual") and entry["status"] != "recovered":
                entry["manual"] = spec["manual"]
                print("  manual step: %s" % spec["manual"])
        elif name == "mediadive":
            arts = fetch_mediadive(limit, full)
            entry |= {"status": "recovered" if all(a.get("ok") for a in arts) else "partial",
                      "artifacts": arts}
        elif name == "mediadb":
            entry |= {"status": "manual", "artifacts": [],
                      "manual": "run tools/mediadb/fetch_mediadb.py (it scrapes %s) and put "
                                "mediadb_raw.json at $MEDIA_SOURCES/mediadb/"
                                % spec["scrape"]}
            print("  manual: %s" % entry["manual"])
        else:
            entry |= {"status": "manual", "artifacts": [], "manual": spec.get("manual", "")}
            print("  manual: %s" % entry.get("manual", ""))
        man["sources"][name] = entry
    save_manifest(man)
    lost = [n for n, e in man["sources"].items() if e.get("status") == "lost"]
    rec = [n for n, e in man["sources"].items() if e.get("status") == "recovered"]
    print("recovered: %s | lost: %s" % (rec or "-", lost or "-"))
    return 0


def write_fixtures() -> int:
    """Vendor a tiny frozen fixture set so the tests run offline."""
    fx = os.path.join(REPO, "tests", "fixtures")
    os.makedirs(fx, exist_ok=True)
    n = 0
    det = os.path.join(SOURCES, "mediadive", "details")
    if os.path.isdir(det):
        picks = sorted(os.listdir(det))[:3]
        for f in picks:
            with open(os.path.join(det, f), encoding="utf-8") as fh:
                obj = json.load(fh)
            with open(os.path.join(fx, "mediadive_detail_%s" % f), "w", encoding="utf-8") as fh:
                json.dump(obj, fh, indent=1)
            n += 1
    bigg = os.path.join(SOURCES, "bigg", "bigg_models_metabolites.txt")
    if os.path.exists(bigg):
        with open(bigg, encoding="utf-8") as fh:
            head = [next(fh) for _ in range(200)]
        with open(os.path.join(fx, "bigg_models_metabolites.head200.txt"), "w",
                  encoding="utf-8") as fh:
            fh.writelines(head)
        n += 1
    print("wrote %d fixture(s) to %s" % (n, os.path.relpath(fx, REPO)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # No argparse `choices` here: for a nargs="*" positional argparse validates the
    # DEFAULT against choices as a single value, so an empty default fails. Validate
    # explicitly instead, and name the valid sources in the error.
    ap.add_argument("names", nargs="*", default=[],
                    help="sources to fetch: " + ", ".join(sorted(SOURCES_SPEC)))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=int, default=25, help="MediaDive detail sample size")
    ap.add_argument("--full", action="store_true", help="MediaDive: fetch every medium")
    ap.add_argument("--fixtures", action="store_true", help="write tests/fixtures/ from the cache")
    a = ap.parse_args()

    if a.list:
        for k, v in sorted(SOURCES_SPEC.items()):
            print("%-11s %-9s %s" % (k, v.get("status", "public"), v["licence"]))
        sys.exit(0)
    if a.fixtures:
        sys.exit(write_fixtures())
    unknown = [n for n in a.names if n not in SOURCES_SPEC]
    if unknown:
        ap.error("unknown source(s) %s; valid: %s"
                 % (", ".join(unknown), ", ".join(sorted(SOURCES_SPEC))))
    names = sorted(SOURCES_SPEC) if a.all else a.names
    if not names:
        ap.error("name a source, or use --all / --list / --fixtures")
    sys.exit(run(names, a.limit, a.full))
