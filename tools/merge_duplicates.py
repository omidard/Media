#!/usr/bin/env python3
"""
Merge duplicate media that are the SAME medium under different record ids.

Conservative, safe criterion: media in the SAME category with an identical
normalised name. (Merging by composition was rejected: our mapping collapses
distinct recipes — e.g. "P2 medium", "M9 + glucose" and "Rich Defined Medium"
all reduce to glucose+minerals+decomposed-AAs — so identical composition does NOT
imply the same medium.)

For each group the most complete record (most components) is kept as canonical;
the others are folded in: their ids go to `merged_ids`, their citations to
`provenance.alt_sources`, and an id->canonical map is written to data/aliases.json
so old ?medium=<id> links still resolve. Merged files are removed.

Run:  python3 tools/merge_duplicates.py [--dry]
"""
import os, re, sys, glob, json, collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    dry = "--dry" in sys.argv
    groups = collections.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        key = (d.get("category"), norm_name(d.get("name")))
        if key[1]:
            groups[key].append((f, d))
    # preserve aliases from previous merges (already-removed dupes must keep resolving)
    apath = os.path.join(REPO, "data", "aliases.json")
    aliases = {}
    if os.path.exists(apath):
        try:
            aliases = json.load(open(apath))
        except Exception:
            aliases = {}
    merged_away = 0
    groups_merged = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # canonical = most components, then lexicographically smallest id (stable)
        members.sort(key=lambda fd: (-len(fd[1].get("components", []) or []), fd[1]["id"]))
        cf, canon = members[0]
        others = members[1:]
        canon.setdefault("merged_ids", [])
        prov = canon.setdefault("provenance", {})
        alt = prov.setdefault("alt_sources", [])
        for of, od in others:
            canon["merged_ids"].append(od["id"])
            aliases[od["id"]] = canon["id"]
            c = (od.get("provenance") or {}).get("citation")
            if c and c not in alt:
                alt.append(c)
            if not dry:
                os.remove(of)
            merged_away += 1
        canon["merged_ids"] = sorted(set(canon["merged_ids"]))
        if not dry:
            with open(cf, "w") as fh:
                json.dump(canon, fh, ensure_ascii=False)
        groups_merged += 1

    if not dry:
        with open(os.path.join(REPO, "data", "aliases.json"), "w") as fh:
            json.dump(aliases, fh, separators=(",", ":"))
    print("groups merged: %d  |  records merged away: %d" % (groups_merged, merged_away))
    print("aliases written: %d -> data/aliases.json" % len(aliases))


if __name__ == "__main__":
    main()
