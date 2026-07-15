#!/usr/bin/env python3
"""Apply recovered full recipes (scratchpad/lowcomp/result_*.json) to the low-component
media records: map each recovered compound name -> BiGG exchange (reusing the MediaDB
salt-dissociation + recover ladder), set concentrations/oxygen, and update provenance
with the base-medium reference + evidence. Never fabricates — unmapped -> uncovered."""
import os, re, sys, json, glob
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.join(HERE, "..", "repo")
LOW = os.path.join(HERE, "..", "..", "lowcomp")
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)
import build_mediadb_media as B   # map_compound(), bound(), DICT

def to_mM(conc, unit):
    if conc is None or unit is None: return None
    u = str(unit).strip().lower()
    try: c = float(conc)
    except: return None
    if u in ("mm", "mmol/l", "mmol/l."): return c
    if u in ("um", "µm", "umol/l", "μm"): return c/1000.0
    if u in ("m", "mol/l"): return c*1000.0
    if u in ("nm",): return c/1e6
    return None   # g/L, %, x — no MW conversion; keep None

def map_recipe(components):
    comps = {}; uncovered = []
    for c in components or []:
        name = (c.get("name") or "").strip()
        if not name: continue
        mM = to_mM(c.get("conc"), c.get("unit"))
        got, unc = B.map_compound({"name": name, "mM": mM, "bigg": None, "kegg": c.get("kegg"), "chebi": c.get("chebi")})
        for x in got:
            x["role"] = c.get("role", "")
            comps.setdefault(x["exchange"], x)
        if unc:
            unc["role"] = c.get("role", "")
            uncovered.append(unc)
    return comps, uncovered

def main():
    apply = "--apply" in sys.argv
    results = sorted(glob.glob(os.path.join(LOW, "result_*.json")))
    print(f"result files: {len(results)}")
    tot_media = tot_before = tot_after = 0; skipped = []
    for rf in results:
        try:
            R = json.load(open(rf))
        except Exception as e:
            print("  BAD json:", os.path.basename(rf), e); continue
        oxygen = (R.get("oxygen") or "facultative").strip().lower()
        if oxygen not in ("aerobic", "anaerobic", "facultative"): oxygen = "facultative"
        conf = R.get("confidence", "medium")
        base_ref = R.get("base_medium_reference", ""); base = R.get("base_medium", "")
        for m in R.get("media", []):
            mid = m.get("id");
            if not mid: continue
            f = os.path.join(REPO, "data", "media", mid + ".json")
            if not os.path.exists(f):
                skipped.append((mid, "missing file")); continue
            comps, uncovered = map_recipe(m.get("components"))
            d = json.load(open(f)); before = len(d.get("components") or [])
            p = d.setdefault("provenance", {})
            # decide: full replacement vs. annotate-only (base unresolved / too few mapped)
            full = (len(comps) >= 3) or (len(comps) >= 2 and conf != "low")
            if not full:
                # do NOT overwrite the composition, but document the base reference + gap
                p["base_medium"] = base; p["base_medium_reference"] = base_ref
                p["verification"] = "recipe partially recovered (base medium unresolved)"
                p["notes"] = (f"Base medium identified as '{base}' ({base_ref}) but its full composition "
                              f"could not be recovered from openly-available sources. {R.get('notes','') or m.get('notes','')}".strip())[:500]
                if apply: json.dump(d, open(f, "w"), ensure_ascii=False)
                skipped.append((mid, f"{len(comps)} mapped (conf={conf}) — annotated, composition kept")); continue
            # aerobic/facultative media must offer O2 uptake (agents don't list O2 as a component)
            if oxygen != "anaerobic" and "EX_o2_e" not in comps:
                comps["EX_o2_e"] = B.mk("o2", "O2 (%s)" % oxygen, None, "regime", "curated")
            d["components"] = sorted(comps.values(), key=lambda x: x["exchange"])
            d["uncovered"] = uncovered
            d["oxygen"] = oxygen; d["aerobic"] = (oxygen != "anaerobic")
            d["n_components"] = len(comps); d["n_mapped"] = len(comps)
            d["n_in_biggr"] = sum(1 for x in comps.values() if x.get("in_biggr"))
            p["verification"] = ("paper-verified (recipe recovered from primary literature)" if conf != "low"
                                  else "recipe recovered (base identity confirmed; some concentrations uncertain — see notes)")
            p["recipe_evidence"] = (m.get("evidence") or "")[:600]
            p["recipe_confidence"] = conf
            p["base_medium"] = base
            p["base_medium_reference"] = base_ref
            p.pop("formulation_warning", None)
            p["notes"] = (f"Full recipe recovered from the primary literature: base medium '{base}' "
                          f"({base_ref}). {p.get('notes','')}".strip())[:500]
            tot_media += 1; tot_before += before; tot_after += len(comps)
            if apply:
                json.dump(d, open(f, "w"), ensure_ascii=False)
    print(f"media updated: {tot_media} | avg components {tot_before/max(tot_media,1):.1f} -> {tot_after/max(tot_media,1):.1f}")
    print(f"skipped: {len(skipped)}")
    for mid, why in skipped: print("   -", mid, "|", why)
    print("DRY RUN (use --apply to write)" if not apply else "WROTE updates")

if __name__ == "__main__":
    main()
