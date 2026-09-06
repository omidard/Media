"""
Regression tests for the naming / grouping / concentration workstream.

Every test names the audited defect it pins. Several of them assert a REFUSAL,
because for most of this corpus the honest outcome is "cannot be determined", not
a number: the resource's core failure was confident presentation of weak evidence,
so a stage that guesses is worse than one that says nothing.

Two layers:
  * pure-function tests over the parsers and detectors (fast, no corpus);
  * an end-to-end run of 50_load_concentrations -> 51_normalize_names over a small
    corpus assembled from the audited records, asserting the corrected shape AND
    asserting that the defect cannot silently return.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGES = os.path.join(REPO, "tools", "stages")
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, STAGES)

import base_media                       # noqa: E402
import load_concentrations as LC        # noqa: E402
import normalize_names as NN            # noqa: E402


# --------------------------------------------------------------------------
# NM-01 -- a quarter POUND is not LB medium.
#
# usda_170772 "WENDY'S, DAVE'S Hot 'N Juicy 1/4 LB, single" was stamped
# base_medium="LB"; 39 of its 43 measured USDA nutrients and all 10 measured
# minerals were replaced by LB's yeast-extract decomposition, and the record was
# ranked tier 1 "expert" citing Bertani 1951.
# --------------------------------------------------------------------------
def test_quarter_pound_burger_is_not_lb_medium():
    assert base_media.detect_base("WENDY'S, DAVE'S Hot 'N Juicy 1/4 LB, single") is None


def test_food_category_can_never_resolve_a_base():
    assert base_media.detect_base("Beef, LB grade", category="food") is None


def test_the_lb_veto_does_not_over_fire_on_a_real_dilution():
    """"1/3 LB Agar (DSMZ J842)" is one-third-strength LB, a real DSMZ variant.

    A veto that swallowed it would trade one defect for another.
    """
    assert base_media.detect_base("1/3 LB Agar") == "LB"


def test_real_lb_still_resolves():
    assert base_media.detect_base("LB (Luria-Bertani) Medium") == "LB"


def test_a_generated_food_description_never_resolves_a_base():
    """701 food descriptions say "plus a standard M9 mineral base"; 0 food NAMES
    say M9. Matching name+description is what put 319 food records one command
    away from being stamped M9."""
    assert base_media.detect_base(
        "measured amino acids, sugars and minerals plus a standard M9 mineral base"
    ) is None


# --------------------------------------------------------------------------
# NM-13 -- a name that means two media must be refused, not resolved by the
# order the patterns happen to sit in.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", [
    "Luria Broth (LB) for in vitro bacterial growth; tryptic soy agar (TSA) for plating",
    "1/2 MRS + 1/2 BHI Agar",
])
def test_multi_base_names_are_refused(name):
    assert base_media.detect_base(name) is None


def test_multi_base_names_report_every_candidate():
    assert sorted(base_media.detect_bases("1/2 MRS + 1/2 BHI Agar")) == ["BHI", "MRS"]


# --------------------------------------------------------------------------
# NM-17 -- raw markup must not reach a display name.
# --------------------------------------------------------------------------
def test_subscript_markup_is_resolved():
    assert NN.clean_name("LB Agar with MnSO<sub>4</sub>") == "LB Agar with MnSO4"


def test_html_entities_are_unescaped():
    assert NN.clean_name("Spizizen&#39;s medium") == "Spizizen's medium"


# --------------------------------------------------------------------------
# NM-13 -- provenance must come OUT of the display string.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,core,tail", [
    ("LB (Luria-Bertani) Medium (DSMZ 381)", "LB (Luria-Bertani) Medium", "(DSMZ 381)"),
    ("LB + 0.1 mg/ml BSA (PMC4019345)", "LB + 0.1 mg/ml BSA", "(PMC4019345)"),
    ("Wasabi (food medium)", "Wasabi", "(food medium)"),
])
def test_provenance_tail_is_split_out(name, core, tail):
    assert NN.split_tail(name) == (core, tail)


# --------------------------------------------------------------------------
# NM-16 -- negation scoping. An automatic name-to-composition repair that
# ignored this would add sulfate to "Sulfate-Free Metako Medium".
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,agent", [
    ("Modified Bacto Tryptic SOY Broth Without Dextrose", "dextrose"),
    ("Sulfate-Free Metako Medium", "sulfate"),
    ("Modified CGM, no formate", "formate"),
])
def test_negated_substrates_are_recorded_absent(name, agent):
    mods, _ = NN.parse_modifiers(name)
    hits = [m for m in mods if agent in m["agent"].lower()]
    assert hits, "the negated substrate was not detected at all"
    assert all(m["polarity"] == "absent" for m in hits)


# --------------------------------------------------------------------------
# NM-02 -- a supplement's dose is not a dilution factor.
# --------------------------------------------------------------------------
def test_a_supplement_dose_is_not_read_as_a_dilution():
    st, _ = NN.parse_strength("LB (LURIA-BERTANI) Agar with 5% NaCl", family_start=0)
    assert st is None


@pytest.mark.parametrize("name,start,factor", [
    ("1/3 LB Agar", 4, 1 / 3.),
    ("Half-CONCENTRATED LB (Luria-Bertani) Medium", 18, 0.5),
    ("0.01% LB Seawater Medium", 6, 0.0001),
])
def test_a_real_dilution_is_parsed(name, start, factor):
    st, _ = NN.parse_strength(name, family_start=start)
    assert st is not None and abs(st["factor"] - factor) < 1e-6


def test_a_consumed_strength_is_not_reattached_as_a_supplement_dose():
    mods, _ = NN.parse_modifiers("0.01% LB Seawater Medium", consumed_spans=[(0, 5)])
    sw = [m for m in mods if m["kind"] == "matrix"]
    assert sw and sw[0]["amount"] is None


# --------------------------------------------------------------------------
# PROV-13 -- significant figures, not decimal places.
# --------------------------------------------------------------------------
def test_molar_mass_from_formula():
    mm, _ = LC.molar_mass_from_formula("C6H12O6")
    assert mm and abs(mm - 180.156) < 0.05


def test_absent_formula_yields_no_mass_and_a_reason():
    mm, why = LC.molar_mass_from_formula(None)
    assert mm is None and why == "no_formula"


def test_a_trace_measurement_survives_the_conversion():
    """biotin at 5e-06 g/L: round(x, 4) gives 0.0, which a modeller reads as
    "absent from the medium". 296 shipped concentrations are zero for this
    reason and every one of them is a real measurement."""
    v = 5e-06 / 244.31 * 1000.0
    assert round(v, 4) == 0.0          # the defect
    assert LC.sigfig(v) > 0            # the fix


# --------------------------------------------------------------------------
# End-to-end: run both registered stages over the audited records.
# --------------------------------------------------------------------------
AUDITED_IDS = [
    "mediadive_381", "mediadive_J842", "mediadive_J1240", "mediadive_J813",
    "mediadive_J1273", "mediadive_J1168", "mediadive_J557", "mediadive_J1040",
    "usda_170772", "mediadive_J491", "std_bg11", "std_lb_broth", "std_tsb",
    "mediadive_1448", "usda_170409", "mdb_10", "mediadive_78",
    "biospecimen_hmdb_blood", "mediadive_1260",
]


@pytest.fixture(scope="module")
def chained():
    """Run 50 -> 51 over a subset corpus; yield (source, corrected) by id."""
    tmp = tempfile.mkdtemp(prefix="mediadb_naming_test_")
    corpus = os.path.join(tmp, "corpus")
    os.makedirs(corpus)
    have = []
    for mid in AUDITED_IDS:
        s = os.path.join(REPO, "data", "media", mid + ".json")
        if os.path.exists(s):
            shutil.copyfile(s, os.path.join(corpus, mid + ".json"))
            have.append(mid)
    if len(have) < 10:
        pytest.skip("audited records are not present in this corpus")
    o1, o2 = os.path.join(tmp, "s50"), os.path.join(tmp, "s51")
    r1 = subprocess.run(
        [sys.executable, os.path.join(STAGES, "50_load_concentrations.py"),
         "--in", corpus, "--out", os.path.join(o1, "media"),
         "--report", os.path.join(o1, "report.json")],
        capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    r2 = subprocess.run(
        [sys.executable, os.path.join(STAGES, "51_normalize_names.py"),
         "--in", os.path.join(o1, "media"), "--out", os.path.join(o2, "media"),
         "--report", os.path.join(o2, "report.json")],
        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    src = {m: json.load(open(os.path.join(corpus, m + ".json"))) for m in have}
    out = {os.path.basename(p)[:-5]: json.load(open(p))
           for p in glob.glob(os.path.join(o2, "media", "*.json"))}
    yield src, out
    shutil.rmtree(tmp, ignore_errors=True)


def test_stages_are_copy_through(chained):
    src, out = chained
    assert set(src) == set(out)


def test_no_flux_bound_is_ever_changed(chained):
    """client/pymediadb builds the COBRApy medium from abs(lower_bound). A
    data-quality stage that moved a bound would silently change every downstream
    simulation."""
    src, out = chained
    for k in src:
        assert ([(c.get("lower_bound"), c.get("upper_bound")) for c in out[k]["components"]]
                == [(c.get("lower_bound"), c.get("upper_bound")) for c in src[k]["components"]])


def test_no_component_is_added_or_dropped(chained):
    src, out = chained
    assert all(len(out[k]["components"]) == len(src[k]["components"]) for k in src)


def test_ids_and_names_are_never_rewritten(chained):
    """Ids are the browser's deep-link key and MediaDive's real namespace; `name`
    is the verbatim upstream join key. Only derived fields may be added."""
    src, out = chained
    assert all(out[k]["id"] == src[k]["id"] for k in src)
    assert all(out[k]["name"] == src[k]["name"] for k in src)


def _components(out):
    return [c for r in out.values() for c in r["components"]]


def test_no_concentration_is_ever_zero(chained):
    _, out = chained
    assert all(c.get("concentration_mM") != 0.0 for c in _components(out))


def test_no_concentration_is_derived_from_a_lost_parent_salt(chained):
    """recipe_g_l on a mediadive_salt component is the PARENT SALT's mass while
    the component is a dissociated ion. Dividing by the ion's mass is wrong by the
    salt/ion ratio, the hydration water and the stoichiometry."""
    _, out = chained
    assert all(not (c.get("mapping_method") == "mediadive_salt"
                    and c.get("concentration_status") == "derived")
               for c in _components(out))


def test_no_food_amount_becomes_a_molar_concentration(chained):
    """A food's nutrient content is an amount per 100 g, not a concentration. mM
    would require a volume basis nobody measured."""
    _, out = chained
    assert all(not ((c.get("quantity") or {}).get("basis") == "per_100g_food"
                    and c.get("concentration_mM") is not None)
               for c in _components(out))


def test_no_quantity_is_derived_for_an_invented_component(chained):
    _, out = chained
    assert all(not (c.get("derived_not_sourced")
                    and c.get("concentration_status") == "derived")
               for c in _components(out))


def test_usda_amounts_are_published_on_their_own_basis(chained):
    """268,697 measured USDA amounts were on disk and never projected (MAP-13).
    They are published as amount_mmol_per_100g, labelled with that basis."""
    _, out = chained
    assert any(c.get("amount_mmol_per_100g") and c.get("amount_basis") == "per_100g_food"
               for c in _components(out))


def test_pipeline_invented_components_are_labelled(chained):
    """Operator decision: segregate and label, never delete."""
    _, out = chained
    assert any(c.get("derived_not_sourced") for c in _components(out))


def test_physically_impossible_concentrations_carry_a_warning(chained):
    """mediadive_78 ships ethanol at 20,620 mM, above neat ethanol's 17,100 --
    a neat-reagent density read as g per litre of medium. Nulling it would hide a
    live upstream bug, so the number carries its own warning instead."""
    _, out = chained
    assert any(c.get("concentration_plausibility") == "implausible_exceeds_pure_substance"
               for c in _components(out))


def test_the_burger_gets_no_family_and_says_why(chained):
    _, out = chained
    b = out["usda_170772"]
    assert b["family"]["id"] is None
    assert b["family"]["refused_reason"] == "category_food_family_not_assigned"


def test_jcm_media_are_attributed_to_jcm_not_dsmz(chained):
    """1,248 of 3,148 "DSMZ" media are JCM or CCAP. There is no "DSMZ Medium
    J1273" -- that PDF 404s at dsmz.de while the JCM page resolves."""
    _, out = chained
    j = out["mediadive_J1273"]
    assert j["collection"] == "JCM"
    assert "MediaDive REST" in (j["collection_evidence"] or "")
    assert j["id"] == "mediadive_J1273", "record ids must never be renamed"


def test_a_named_modifier_is_typed_and_honestly_marked(chained):
    """The name promises 5% NaCl; the composition has EX_na1_e and EX_cl_e both
    at an unconstrained -1000. The modifier is captured with its dose AND marked
    as not represented, so the name stops making a promise the data cannot keep."""
    _, out = chained
    nacl = [m for m in out["mediadive_J1240"]["modifiers"]
            if m["agent"].upper() == "NACL"]
    assert nacl and nacl[0]["amount"] == 5.0 and nacl[0]["unit"] == "%"
    assert nacl[0]["reflected_in_composition"] is False


def test_a_record_states_its_own_compositional_limitation(chained):
    _, out = chained
    r = out["mediadive_J1240"]
    assert r["composition_distinguishes_modifiers"] is False
    assert r["composition_limitation"]


def test_an_ambiguous_name_is_refused_with_both_candidates(chained):
    _, out = chained
    f = out["mediadive_J491"]["family"]
    assert f["id"] is None
    assert set(f["candidates"]) == {"bhi", "mrs"}


def test_a_canonical_reference_record_is_recognised(chained):
    _, out = chained
    assert out["std_lb_broth"]["family"]["method"] == "canonical_reference"


def test_every_unassigned_family_carries_a_refusal_reason(chained):
    """An absent value must say why it is absent. Silence is what let 439 media
    with unknown oxygen render as "anaerobic"."""
    _, out = chained
    for r in out.values():
        if r["family"]["id"] is None:
            assert r["family"].get("refused_reason")
