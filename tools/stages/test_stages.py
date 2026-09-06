#!/usr/bin/env python3
"""
Regression tests for the naming / concentration stages.

Each test is pinned to a specific audited defect and names it. Run:

    python3 tools/stages/test_stages.py

Exits non-zero on any failure. These are the checks that must stay green for the
corrections to remain corrections; several of them assert a REFUSAL, because the
honest outcome for most of this corpus is "cannot be derived", not a number.
"""
import os, sys, json, re, subprocess, tempfile, glob

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)

import base_media  # noqa: E402
import normalize_names as NN  # noqa: E402
import load_concentrations as LC  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s   %s" % (name, detail))
        FAILS.append(name)


print("== NM-01: a quarter POUND is not LB medium ==")
check("burger name yields no base",
      base_media.detect_base("WENDY'S, DAVE'S Hot 'N Juicy 1/4 LB, single") is None)
check("food category can never yield a base",
      base_media.detect_base("Beef, LB grade", category="food") is None)
check("one-third-strength LB medium is STILL LB (the veto must not over-fire)",
      base_media.detect_base("1/3 LB Agar") == "LB")
check("real LB still resolves",
      base_media.detect_base("LB (Luria-Bertani) Medium") == "LB")
check("generated food description never yields a base",
      base_media.detect_base(
          "measured amino acids, sugars and minerals plus a standard M9 mineral base") is None)

print("== NM-13: a name matching two bases must refuse, not pick by pattern order ==")
check("LB-for-growth + TSA-for-plating refuses",
      base_media.detect_base(
          "Luria Broth (LB) for in vitro bacterial growth; tryptic soy agar (TSA) for plating") is None)
check("half MRS + half BHI refuses",
      base_media.detect_base("1/2 MRS + 1/2 BHI Agar") is None)
check("both bases are reported as candidates",
      sorted(base_media.detect_bases("1/2 MRS + 1/2 BHI Agar")) == ["BHI", "MRS"])

print("== NM-17: HTML markup must not reach a display name ==")
check("subscript tag resolved",
      NN.clean_name("LB Agar with MnSO<sub>4</sub>") == "LB Agar with MnSO4")
check("entity unescaped",
      NN.clean_name("Spizizen&#39;s medium") == "Spizizen's medium")

print("== NM-13: provenance must come out of the display string, not stay in it ==")
check("DSMZ tail split",
      NN.split_tail("LB (Luria-Bertani) Medium (DSMZ 381)")
      == ("LB (Luria-Bertani) Medium", "(DSMZ 381)"))
check("PMC tail split",
      NN.split_tail("LB + 0.1 mg/ml BSA (PMC4019345)")
      == ("LB + 0.1 mg/ml BSA", "(PMC4019345)"))

print("== NM-16: negation scoping ==")
mods, _ = NN.parse_modifiers("Modified Bacto Tryptic SOY Broth Without Dextrose")
dex = [m for m in mods if m["agent"].lower() == "dextrose"]
check("'Without Dextrose' is recorded as ABSENT", dex and dex[0]["polarity"] == "absent")
mods, _ = NN.parse_modifiers("Sulfate-Free Metako Medium")
su = [m for m in mods if "sulfate" in m["agent"].lower()]
check("'Sulfate-Free' never asserts sulfate present",
      all(m["polarity"] == "absent" for m in su))
mods, _ = NN.parse_modifiers("Modified CGM, no formate")
fo = [m for m in mods if "formate" in m["agent"].lower()]
check("'no formate' is ABSENT", fo and fo[0]["polarity"] == "absent")

print("== NM-02: a supplement dose is not a dilution factor ==")
st, _ = NN.parse_strength("LB (LURIA-BERTANI) Agar with 5% NaCl", family_start=0)
check("5% NaCl is NOT read as 5%-strength LB", st is None, str(st))
st, _ = NN.parse_strength("1/3 LB Agar", family_start=4)
check("1/3 LB Agar is one-third strength", st and abs(st["factor"] - 1 / 3.) < 1e-4, str(st))
st, _ = NN.parse_strength("Half-CONCENTRATED LB (Luria-Bertani) Medium", family_start=18)
check("Half-CONCENTRATED is 0.5", st and st["factor"] == 0.5, str(st))
mods, _ = NN.parse_modifiers("0.01% LB Seawater Medium", consumed_spans=[(0, 5)])
sw = [m for m in mods if m["kind"] == "matrix"]
check("a strength already consumed is not re-attached as a seawater dose",
      sw and sw[0]["amount"] is None, str(sw))

print("== formula -> molar mass ==")
mm, why = LC.molar_mass_from_formula("C6H12O6")
check("glucose mass ~180.16", mm and abs(mm - 180.156) < 0.05, str(mm))
mm, why = LC.molar_mass_from_formula(None)
check("no formula -> no mass, with a reason", mm is None and why == "no_formula")
check("4 significant figures, not 4 decimal places (PROV-13 biotin case)",
      LC.sigfig(5e-06 / 244.31 * 1000.0) > 0)
check("round(x,4) would have produced 0.0 here",
      round(5e-06 / 244.31 * 1000.0, 4) == 0.0)

print("== end-to-end on an audited sample ==")
IDS = ("mediadive_381,mediadive_J842,mediadive_J1240,mediadive_J813,"
       "mediadive_J1273,mediadive_J1168,mediadive_J557,mediadive_J1040,"
       "usda_170772,mediadive_J491,std_bg11,std_lb_broth,std_tsb,"
       "mediadive_1448,usda_170409,mdb_10,mediadive_78,biospecimen_hmdb_blood")
tmp = tempfile.mkdtemp(prefix="mediadb_stage_test_")
o1, o2 = os.path.join(tmp, "s1"), os.path.join(tmp, "s2")
r1 = subprocess.run([sys.executable, os.path.join(HERE, "load_concentrations.py"),
                     "--out", o1, "--ids", IDS], capture_output=True, text=True)
check("load_concentrations exits 0 (all assertions pass)", r1.returncode == 0,
      r1.stderr[-500:])
r2 = subprocess.run([sys.executable, os.path.join(HERE, "normalize_names.py"),
                     "--in", os.path.join(o1, "media"), "--out", o2, "--ids", IDS],
                    capture_output=True, text=True)
check("normalize_names exits 0 (all assertions pass)", r2.returncode == 0,
      r2.stderr[-500:])

if r1.returncode == 0 and r2.returncode == 0:
    rep1 = json.load(open(os.path.join(o1, "reports", "concentrations_report.json")))
    src = {os.path.basename(p): json.load(open(p))
           for p in glob.glob(os.path.join(REPO, "data", "media", "*.json"))
           if os.path.basename(p)[:-5] in IDS.split(",")}
    out = {os.path.basename(p): json.load(open(p))
           for p in glob.glob(os.path.join(o2, "media", "*.json"))}

    check("no bound was changed by either stage", all(
        [(c.get("lower_bound"), c.get("upper_bound")) for c in out[k]["components"]]
        == [(c.get("lower_bound"), c.get("upper_bound")) for c in src[k]["components"]]
        for k in src))
    check("no component was added or dropped",
          all(len(out[k]["components"]) == len(src[k]["components"]) for k in src))
    check("no id was changed", all(out[k]["id"] == src[k]["id"] for k in src))
    check("no name was overwritten", all(out[k]["name"] == src[k]["name"] for k in src))
    check("no record was deleted", len(out) == len(src))

    allc = [c for r in out.values() for c in r["components"]]
    check("A3: no concentration_mM is ever 0.0",
          all(c.get("concentration_mM") != 0.0 for c in allc))
    check("A4: no concentration derived from a parent-salt-lost component",
          all(not (c.get("mapping_method") == "mediadive_salt"
                   and c.get("concentration_status") == "derived") for c in allc))
    check("A5: no per-100g food amount written into concentration_mM",
          all(not ((c.get("quantity") or {}).get("basis") == "per_100g_food"
                   and c.get("concentration_mM") is not None) for c in allc))
    check("A6: no quantity derived for a pipeline-invented component",
          all(not (c.get("derived_not_sourced")
                   and c.get("concentration_status") == "derived") for c in allc))
    check("USDA amounts ARE published, on their own honest basis",
          any(c.get("amount_mmol_per_100g") and c.get("amount_basis") == "per_100g_food"
              for c in allc))
    check("invented components are labelled derived_not_sourced",
          any(c.get("derived_not_sourced") for c in allc))
    check("physically impossible stated concentrations carry a warning",
          any(c.get("concentration_plausibility") == "implausible_exceeds_pure_substance"
              for c in allc))

    burger = out["usda_170772.json"]
    check("NM-01: the burger has no family", burger["family"]["id"] is None)
    check("NM-01: and says why",
          burger["family"]["refused_reason"] == "category_food_family_not_assigned")

    j1273 = out["mediadive_J1273.json"]
    check("NM-03: J1273's collection is JCM, not DSMZ", j1273["collection"] == "JCM")
    check("NM-03: attribution comes from MediaDive's own field",
          "MediaDive REST" in (j1273.get("collection_source") or ""))
    check("NM-03: the record id is untouched", j1273["id"] == "mediadive_J1273")

    j1240 = out["mediadive_J1240.json"]
    nacl = [m for m in j1240["modifiers"] if m["agent"].upper() == "NACL"]
    check("NM-02: '5% NaCl' is captured as a typed modifier with its dose",
          nacl and nacl[0]["amount"] == 5.0 and nacl[0]["unit"] == "%")
    check("NM-02: and is honestly marked as NOT represented in the composition",
          nacl and nacl[0]["reflected_in_composition"] is False)
    check("NM-02: the record states its own limitation",
          j1240.get("composition_distinguishes_modifiers") is False
          and j1240.get("composition_limitation"))

    j491 = out["mediadive_J491.json"]
    check("NM-13: '1/2 MRS + 1/2 BHI' refuses a family and lists both candidates",
          j491["family"]["id"] is None and set(j491["family"]["candidates"]) == {"bhi", "mrs"})

    check("std_lb_broth is recognised as the canonical LB reference",
          out["std_lb_broth.json"]["family"]["method"] == "canonical_reference")

print()
if FAILS:
    print("FAILED: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL TESTS PASSED")
