#!/usr/bin/env python3
"""
Curate the oxygen regime of every medium — stop asserting "aerobic" without basis.

We previously set aerobic=True almost everywhere (and gave every medium O2 uptake at
-10), which is wrong for obligate-anaerobe media (Desulfovibrio, Methanogenium,
Clostridium ...) and for low-O2 body fluids (amniotic, bile, gut). This assigns an
explicit `oxygen` regime with a reason and sets EX_o2_e accordingly:

  anaerobic   -> EX_o2_e lower_bound 0 (no O2). aerobic=False.
  aerobic     -> O2 available (-10), and the source actually indicates aerobic growth.
  facultative -> O2 available (-10) but NOT asserted as required; the modeller chooses.
                 This is the honest default for food substrates and unspecified media.

`aerobic` (bool) is kept for back-compat and means "O2 available in the medium"
(True for aerobic + facultative, False for anaerobic).

Run:  python3 tools/curate_oxygen.py [--dry]
"""
import os, re, sys, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MEDIA = os.path.join(REPO, "data", "media")

# obligate/strict anaerobe signals in a medium name
ANAEROBE = re.compile(
    r"anaerob|methanogen|methanococc|methanobacter|methanosarc|methanobrevibacter|"
    r"clostrid|desulfo|desulfu|sulfate[-\s]?reduc|sulfur[-\s]?reduc|thiosulfate[-\s]?reduc|"
    r"syntroph|geobacter|thermoclostrid|reinforced\s+clostridial|wilkins[-\s]?chalgren|"
    r"butyrivibrio|ruminococc|bacteroides|prevotella|fusobacter|veillonell|acetogen|"
    r"homoacetogen|\brumen\b|thermotoga|dehalococcoid|dehalobacter|acetobacterium|"
    r"under\s+n2|n2/co2|n2:co2|strictly\s+anaerob", re.I)
# explicit aerobic signal
AEROBE = re.compile(r"\baerobic\b|\baerobe\b|(?<!an)aerobically", re.I)

# biospecimen id fragment -> regime (physiology-based)
BIOSPEC = [
    (re.compile(r"feces|faec|gut|stool|colon|intestin", re.I), "anaerobic",
     "gut/faecal lumen is strictly anaerobic"),
    (re.compile(r"rumen", re.I), "anaerobic", "rumen is a strictly anaerobic fermenter"),
    (re.compile(r"bile", re.I), "anaerobic", "bile duct/gallbladder is a low-O2 internal fluid"),
    (re.compile(r"amniotic", re.I), "anaerobic", "amniotic fluid is a low-O2 intrauterine fluid"),
    (re.compile(r"cerebrospinal|csf", re.I), "facultative", "CSF O2 is low; treat as modeller's choice"),
    (re.compile(r"blood|serum|plasma", re.I), "facultative",
     "blood/serum O2 is limited and venous/arterial-dependent; not an aerobic broth"),
    (re.compile(r"milk|colostrum", re.I), "facultative", "milk O2 depends on handling"),
    (re.compile(r"urine|saliva|sweat|skin", re.I), "aerobic", "externally-exposed body fluid/surface"),
]


def regime_for(d):
    name = d.get("name") or ""
    cat = d.get("category")
    cur_anaer = (d.get("aerobic") is False) or (d.get("oxygen") == "anaerobic")
    # 1) name says anaerobic -> anaerobic (highest priority)
    if ANAEROBE.search(name):
        return "anaerobic", "medium/organism is anaerobic (from name)"
    # 2) biospecimen physiology
    if cat == "biospecimen":
        for rx, reg, why in BIOSPEC:
            if rx.search(name) or rx.search(d.get("id", "")):
                return reg, why
        return "facultative", "internal fluid; O2 availability is a modelling choice"
    # 3) name says aerobic -> aerobic
    if AEROBE.search(name):
        return "aerobic", "medium indicates aerobic growth (from name)"
    # 4) already curated anaerobic (e.g. builder set aerobic False) -> keep
    if cur_anaer:
        return "anaerobic", "retained anaerobic designation"
    # 5) food and everything else with no O2 info -> facultative (do not assert aerobic)
    if cat == "food":
        return "facultative", "food substrate; O2 availability is a simulation condition, not a property of the food"
    return "facultative", "no oxygen requirement specified; O2 available but not asserted"


def main():
    dry = "--dry" in sys.argv
    from collections import Counter
    tally = Counter(); changed = 0; o2fixed = 0
    for f in sorted(glob.glob(os.path.join(MEDIA, "*.json"))):
        d = json.load(open(f))
        reg, why = regime_for(d)
        tally[(d.get("category"), reg)] += 1
        old_aer = d.get("aerobic")
        new_aer = (reg != "anaerobic")
        # set O2 exchange bound
        o2 = None
        for c in d.get("components", []):
            if c.get("exchange") == "EX_o2_e":
                o2 = c
        if reg == "anaerobic":
            if o2 is not None and o2.get("lower_bound", 0) < 0:
                o2["lower_bound"] = 0.0; o2fixed += 1
        else:
            if o2 is not None and o2.get("lower_bound") == 0.0:
                o2["lower_bound"] = -10.0; o2fixed += 1
        dirty = (d.get("oxygen") != reg) or (old_aer != new_aer)
        d["oxygen"] = reg
        d["oxygen_note"] = why
        d["aerobic"] = new_aer
        if dirty or o2fixed:
            changed += 1
        if not dry:
            with open(f, "w") as fh:
                json.dump(d, fh, ensure_ascii=False)
    print("oxygen regime by category:")
    for k, v in sorted(tally.items()):
        print(f"  {k}: {v}")
    print(f"records written: {0 if dry else changed} | O2 bounds corrected: {o2fixed}")


if __name__ == "__main__":
    main()
