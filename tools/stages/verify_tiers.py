#!/usr/bin/env python3
"""Draw a deterministic stratified verification sample from a remapped corpus.

The point of an evidence tier is that a reader can trust it. That is only worth
something if somebody measured how often each tier is actually right, so this
script draws a reproducible sample per tier -- the 20 highest-volume distinct
(source_name -> BiGG id) decisions plus 25 drawn uniformly from the tail -- and
writes it out for a human to adjudicate one row at a time.

Sampling distinct DECISIONS rather than rows is deliberate: one adjudication of
"MUFA 18:1 -> ocdcea" settles 6,703 component rows, and the report states both
counts so the coverage is not overstated.

    python3 tools/stages/verify_tiers.py <remapped_media_dir> [--out sample.tsv]

Adjudications are recorded in tools/curation/tier_verification.tsv; re-running
this script reproduces the same sample, so the recorded verdicts stay attached
to the rows they were made about.
"""
import argparse, collections, csv, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

SEED = 20260906
TOP_N = 20
TAIL_N = 25


def collect(media_dir):
    per = collections.defaultdict(collections.Counter)
    for name in sorted(os.listdir(media_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(media_dir, name), encoding="utf-8") as fh:
            d = json.load(fh)
        for c in d.get("components") or []:
            src = c.get("source_name")
            if not src and c.get("source_name_candidates"):
                src = "|".join(c["source_name_candidates"])
            if not src:
                src = c.get("name")
            per[c.get("evidence_tier")][(src, c.get("bigg_metabolite"),
                                         c.get("proxy_for") and "|".join(c["proxy_for"]) or "")] += 1
    return per


def draw(per):
    rnd = random.Random(SEED)
    out = {}
    for tier, ctr in per.items():
        pairs = sorted(ctr.items(), key=lambda kv: (-kv[1], str(kv[0])))
        tail = pairs[TOP_N:]
        out[tier] = pairs[:TOP_N] + rnd.sample(tail, min(TAIL_N, len(tail)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media_dir")
    ap.add_argument("--out", default=os.path.join(TOOLS, "curation", "tier_verification_sample.tsv"))
    args = ap.parse_args()

    with open(os.path.join(TOOLS, "bigg_metabolite_dict.json"), encoding="utf-8") as fh:
        D = json.load(fh)
    per = collect(args.media_dir)
    sample = draw(per)

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["evidence_tier", "source_name", "bigg_metabolite", "target_name",
                    "formula", "inchikey", "proxy_for", "n_rows_this_decision"])
        for tier in sorted(sample, key=lambda t: -sum(per[t].values())):
            for (src, b, proxy), n in sample[tier]:
                r = D.get(b) or {}
                x = r.get("xrefs") or {}
                w.writerow([tier, src, b or "", r.get("name") or "", x.get("formula") or "",
                            x.get("inchikey") or "", proxy, n])

    print(f"{'tier':22s} {'rows':>9s} {'decisions':>10s} {'sampled':>8s} {'rows covered':>13s}")
    tot_s = tot_r = 0
    for tier in sorted(per, key=lambda t: -sum(per[t].values())):
        rows = sum(per[tier].values())
        covered = sum(n for _, n in sample[tier])
        tot_s += len(sample[tier]); tot_r += covered
        print(f"{tier:22s} {rows:>9,} {len(per[tier]):>10,} {len(sample[tier]):>8} "
              f"{covered:>10,} ({100*covered/rows:.1f}%)")
    print(f"\n{tot_s} decisions sampled, covering {tot_r:,} component rows")
    print(f"sample written to {args.out}")


if __name__ == "__main__":
    main()
