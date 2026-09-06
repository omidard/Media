#!/usr/bin/env python3
"""
Component-level statistics for the browser and the /data/media_stats.json endpoint.

Run from anywhere:  python3 tools/build_media_stats.py [--media DIR] [--out FILE]

Audit fixes carried by this file (STALE-01)
-------------------------------------------
* This builder had NO caller: it is in no workflow and in no README instruction,
  so media_stats.json was never regenerated after its initial import. It shipped
  12,387 media against 13,515 on disk — an 8.3% shortfall on a published endpoint
  that the landing page fetches. It is now part of `make derived` and of CI.
* Its paths were bare relative strings (`data/media/*.json`, `tools/...`), so it
  only worked from the repo root. They are anchored to __file__.
* The exchange tally silently dropped every `mapping_method == "mineral_base"`
  component (89,644 rows), so a chart labelled "most common components" was not
  the most common components: the unfiltered leader is EX_pi_e, the filtered one
  is EX_thm_e. Both tallies are now emitted, each with the filter that produced
  it stated in the payload, so the chart can label what it is showing.
* An empty media directory is a hard error rather than a zero-row artifact.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(media_dir, out_path, dict_path):
    files = sorted(glob.glob(os.path.join(media_dir, "*.json")))
    if not files:
        raise SystemExit("FATAL: no media found in %s — refusing to write an empty "
                         "media_stats.json over a published endpoint." % media_dir)

    cat = Counter(); src_v = Counter(); src = Counter(); grp = Counter()
    exch_all = Counter(); exch_nomineral = Counter(); n_no_exchange = [0]
    ncomp = []
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        cat[d["category"]] += 1
        src[d["provenance"]["source_type"]] += 1
        # source_type is the record's own free-text label and is not a resolved
        # identity (SCHEMA-02: 472 records carry a database name in it). The verified
        # identity written by 20_stamp_provenance is published beside it, not instead
        # of it, so a consumer of the old key keeps working.
        src_v[(d["provenance"].get("source_name") or "(unresolved)")] += 1
        if d.get("food_group"):
            grp[d["food_group"]] += 1
        ncomp.append(d["n_components"])
        for c in d["components"]:
            # A null exchange is the curated verdict that no single exchange is
            # defensible for this ingredient (yeast extract, peptone, a trace-element
            # solution), written by 40_remap_components. It is not a compound and must
            # not become a Counter key; n_components_without_exchange reports how many
            # were skipped, so the tally still accounts for every component.
            ex = c.get("exchange")
            if ex is None:
                n_no_exchange[0] += 1
                continue
            exch_all[ex] += 1
            if c.get("mapping_method") != "mineral_base":
                exch_nomineral[ex] += 1

    with open(dict_path, encoding="utf-8") as fh:
        dic = json.load(fh)

    def nm(ex):
        m = re.match(r"EX_(.+)_e$", ex)
        b = m.group(1) if m else ex
        return dic.get(b, {}).get("name", b)

    def top(counter, n=40):
        return [{"exchange": e, "name": nm(e), "n_media": c}
                for e, c in counter.most_common(n)]

    out = {
        "schema": "mediadb-media-stats/2",
        "built_at": dt.date.today().isoformat(),
        "total": len(files),
        "n_components_without_exchange": n_no_exchange[0],
        "by_category": dict(cat),
        "by_source": dict(src),
        "by_verified_source": dict(src_v),
        "by_food_group": dict(grp.most_common()),
        # Two tallies, each labelled with the filter that produced it. The browser
        # must state which one it is drawing (STALE-01).
        "top_exchanges": top(exch_all),
        "top_exchanges_filter": "none — every component row",
        "top_exchanges_excluding_mineral_base": top(exch_nomineral),
        "top_exchanges_excluding_mineral_base_filter":
            "components with mapping_method == 'mineral_base' excluded "
            "(the injected mineral base, not part of the cited recipe)",
        "ncomp_min": min(ncomp),
        "ncomp_median": int(sorted(ncomp)[len(ncomp) // 2]),
        "ncomp_max": max(ncomp),
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=0)
    print("stats:", len(files), "media | cats", dict(cat), "| sources", dict(src))
    print("top (unfiltered):", [(e["name"], e["n_media"]) for e in out["top_exchanges"][:5]])
    print("top (no mineral base):",
          [(e["name"], e["n_media"]) for e in out["top_exchanges_excluding_mineral_base"][:5]])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", default=os.path.join(REPO, "data", "media"))
    ap.add_argument("--out", default=os.path.join(REPO, "data", "media_stats.json"))
    ap.add_argument("--dict", default=os.path.join(REPO, "tools", "bigg_metabolite_dict.json"))
    a = ap.parse_args()
    build(os.path.abspath(a.media), os.path.abspath(a.out), os.path.abspath(a.dict))
