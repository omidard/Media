"""Stage 20 (licence, source identity, provenance honesty) and stage 39 (honest coverage).

Every fixture below is a case the audit proved wrong, written out as a record so the suite
runs with no corpus present. Each test also asserts that the defect cannot silently return —
an unlisted mapping_method or an unresolvable source must RAISE, never fall through to a
default, because a silent default is the failure class this resource was audited for.
"""
import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGES = os.path.join(REPO, "tools", "stages")
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, STAGES)


def _load(name):
    """Import a stage module whose filename starts with a digit."""
    spec = importlib.util.spec_from_file_location(
        name.replace(".py", ""), os.path.join(STAGES, name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S20 = _load("20_stamp_provenance.py")
S39 = _load("39_recompute_coverage.py")
from stagelib import Report, StageError  # noqa: E402
from source_identity import resolve      # noqa: E402


@pytest.fixture
def rep():
    r = Report("test", "0", "/in", "/out")
    r.n_in = 1
    return r


def comp(method, **kw):
    c = {"name": "x", "exchange": "EX_x_e", "mapping_method": method,
         "mapping_confidence": "convention", "lower_bound": -1.0}
    c.update(kw)
    return c


def rec(mid, prov, components=None, uncovered=None, pct=100.0, name="m"):
    return {"id": mid, "name": name, "provenance": dict(prov),
            "components": list(components or []), "uncovered": list(uncovered or []),
            "coverage": {"pct_covered": pct}}


MEDIADIVE = {"source_type": "database", "doi": "10.1093/nar/gkac803"}


# ----------------------------------------------------------------- source identity
def test_identity_is_resolved_from_evidence_not_from_the_record_id():
    """build_index.py infers source from `idv.startswith('mediadive_')`. resolve() cannot:
    it is never given the id."""
    assert "id" not in resolve.__code__.co_varnames
    ident = resolve(dict(MEDIADIVE, citation="DSMZ MediaDive ...; DSMZ Medium J557: X.",
                         url="https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=557"))
    assert ident.source_id == "dsmz_mediadive"
    # the source is evidenced by the aggregator's DOI plus its name in the citation;
    # the URL host is what separates the collection behind it
    assert "provenance.doi" in ident.evidence and "MediaDive" in ident.evidence
    assert ident.collection == "JCM" and "url host" in ident.collection_evidence


def test_an_unresolvable_source_raises_and_is_never_guessed_into_a_bucket(rep):
    r = rec("mystery", {"source_type": "?", "citation": "somewhere", "doi": "", "url": ""})
    with pytest.raises(StageError) as e:
        S20.transform(r, rep)
    assert "never guesses" in str(e.value)


# ----------------------------------------------------------------- the DSMZ mis-stamping
def test_jcm_medium_is_attributed_to_jcm_and_the_original_citation_is_kept(rep):
    r = rec("mediadive_J557",
            dict(MEDIADIVE,
                 citation="DSMZ MediaDive (Koblitz J et al., Nucleic Acids Res 2023); "
                          "DSMZ Medium J557: ALKALINE LB AGAR.",
                 url="https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=557"),
            [comp("mediadive_defined")], name="Alkaline LB Agar (DSMZ J557)")
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["collection"] == "JCM"
    assert p["collection_medium_id"] == "557"          # confirmed against GRMD= in the URL
    assert "JCM medium 557" in p["citation"] and "DSMZ Medium" not in p["citation"]
    assert p["citation_original"].startswith("DSMZ MediaDive")   # never destroyed
    assert p["attribution_conflict"]["suggested_name"] == "Alkaline LB Agar (JCM 557, via MediaDive)"
    assert r["name"] == "Alkaline LB Agar (DSMZ J557)"           # renaming is the naming stage's job


def test_a_ccap_medium_id_that_cannot_be_verified_stays_null(rep):
    r = rec("mediadive_C85",
            dict(MEDIADIVE,
                 citation="DSMZ MediaDive (...); DSMZ Medium C85: RPL/0.01%RPA.",
                 url="https://www.ccap.ac.uk/media/pdfrecipes/RPL.pdf"),
            [comp("mediadive_salt")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["collection"] == "CCAP"
    assert p["collection_medium_id"] is None           # absent is null, never a guess
    assert "CCAP medium (MediaDive C85)" in p["citation"]


# ----------------------------------------------------------------- licensing
def test_bovine_records_resolve_to_bmdb_not_hmdb(rep):
    """build_index.py:8 files every biospecimen_* under 'Published (HMDB-derived)', so bovine
    rumen and colostrum ship labelled human-metabolome-derived."""
    r = rec("biospecimen_bmdb_rumen",
            {"source_type": "database", "doi": "10.3390/metabo10060233",
             "citation": "Bovine Metabolome Database (BMDB; Foroutan A et al., 2020).",
             "url": "https://doi.org/10.3390/metabo10060233"},
            [comp("hmdb")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["source_id"] == "bmdb"
    # bovinedb.ca states no Creative Commons licence at all, only a permission clause.
    assert p["license"] == "custom-permission-required"
    assert p["commercial_use"] == "permission_required" and p["commercial_use_ok"] is False


@pytest.mark.parametrize("mid,prov,lic,ok", [
    ("food_FOOD00044",
     {"source_type": "database", "citation": "FooDB v2020-04-07.", "doi": "",
      "url": "https://foodb.ca/downloads"}, "CC-BY-NC-4.0", False),
    ("mdb_11",
     {"source_type": "MediaDB (ISB defined media)", "citation": "Rodriguez-moya et al, 2010",
      "doi": None, "url": "https://mediadb.systemsbiology.net/defined_media/media/11/"},
     "all-rights-reserved", False),
    ("usda_1", {"source_type": "database", "citation": "USDA FoodData Central (FDC ID 1).",
                "doi": "", "url": "https://fdc.nal.usda.gov/food-details/1/nutrients"},
     "CC0-1.0", True),
])
def test_non_commercial_sources_are_never_relicensed_as_cc_by(rep, mid, prov, lic, ok):
    r = rec(mid, prov, [comp("name")])
    S20.transform(r, rep)
    assert r["provenance"]["license"] == lic
    assert r["provenance"]["commercial_use_ok"] is ok


def test_every_stamped_licence_carries_the_evidence_it_rests_on(rep):
    r = rec("food_FOOD00044",
            {"source_type": "database", "citation": "FooDB.", "doi": "",
             "url": "https://foodb.ca/downloads"}, [comp("name")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["license_terms_url"] and p["license_terms_retrieved"]
    assert p["license_terms_verification"] in (
        "first_party", "first_party_via_web_archive", "project_assertion")


def test_a_licence_that_cannot_be_settled_says_so_instead_of_choosing(rep):
    """5 classic formulations carry a MediaDive URL, so their composition may come from a
    CC BY source requiring attribution. Flagged, not silently claimed."""
    r = rec("std_marine_broth_2216",
            {"source_type": "standard", "citation": "Marine Broth 2216 — ZoBell CE 1941.",
             "doi": "", "url": "https://mediadive.dsmz.de/medium/514"}, [comp("wellknown_curation")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["license_review_required"] is True
    assert "mediadive.dsmz.de" in p["license_review_reason"]


def test_the_licence_schedule_and_the_source_vocabulary_cannot_drift_apart():
    from source_identity import SOURCE_IDS
    assert set(S20.load_licenses()) == set(SOURCE_IDS)


# ----------------------------------------------------------------- citations
def test_an_author_year_stub_is_reported_unresolved_rather_than_guessed(rep):
    """Resolving 'Rodriguez-moya et al, 2010' against Crossref would turn a visible gap into
    an invisible fabrication."""
    r = rec("mdb_11", {"source_type": "MediaDB (ISB defined media)",
                       "citation": "Rodriguez-moya et al, 2010", "doi": None,
                       "url": "https://mediadb.systemsbiology.net/defined_media/media/11/"},
            [comp("mediadb_bigg")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["citation_resolved"] is False and p["primary_identifier"] is None
    assert p["citation_type"] == "database_record" and p["has_primary_citation"] is False


def test_a_database_paper_doi_is_not_counted_as_a_primary_source(rep):
    """3,148 records carry the MediaDive database paper's DOI. It describes the database, not
    any medium — counting it as a primary work is what makes '91.8% of DOIs are one DOI' look
    like source diversity."""
    r = rec("mediadive_1", dict(MEDIADIVE,
                                citation="DSMZ MediaDive (...); DSMZ Medium 1: NUTRIENT AGAR.",
                                url="https://www.dsmz.de/x.pdf"), [comp("base")])
    S20.transform(r, rep)
    assert r["provenance"]["primary_identifier"] is None
    assert r["provenance"]["citation_type"] == "collection_catalog"


def test_a_pmc_id_in_the_url_is_recovered_even_when_the_doi_field_is_empty(rep):
    r = rec("growthlit_PMC4594890", {"source_type": "literature", "doi": "",
                                     "citation": "Medium from PMC4594890 (GrowthDB).",
                                     "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4594890/"},
            [comp("growthdb_curation")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["primary_identifier"] == {"type": "pmcid", "value": "PMC4594890"}
    assert p["has_primary_citation"] is True


# ----------------------------------------------------------------- verification honesty
def test_a_rejected_record_is_relabelled_and_not_quarantined(rep):
    r = rec("complexlit_PMC3946380_obgm_oral_bacterial_growth_medium_u_13c_glyc",
            {"source_type": "literature", "doi": "",
             "citation": "Medium composition from PMC3946380 (see GrowthDB record).",
             "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3946380/",
             "verification": "paper-verified (recipe recovered from primary literature)",
             "verification_note": "This paper USES OBGM but does not print its composition."},
            [comp("complex_decomposition", derived_from="beef extract")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["verification_status"] == "reconstructed-from-cited-references"
    assert p["verification_original"].startswith("paper-verified")
    assert "unavailable" in p["verification_downgrade_reason"]
    assert len(r["components"]) == 1          # relabelled, never emptied


def test_a_record_the_pass_rejected_with_no_label_gets_an_explicit_status(rep):
    r = rec("growthlit_PMC2998477_pseudomonas_basal_mineral_medium_pbm",
            {"source_type": "literature", "doi": "",
             "citation": "Medium from PMC2998477 (GrowthDB).",
             "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2998477/"},
            [comp("growthdb_curation")])
    S20.transform(r, rep)
    assert r["provenance"]["verification_status"] == "rejected-by-verification-pass"


def test_an_honest_verification_label_is_left_alone(rep):
    r = rec("bhi", {"source_type": "standard", "citation": "BHI standard formulation.",
                    "doi": "", "url": "",
                    "verification": "expert-curated (canonical formulation)"},
            [comp("wellknown_curation")])
    S20.transform(r, rep)
    p = r["provenance"]
    assert p["verification_status"] == "expert-curated"
    assert p["verification_downgrade_reason"] is None


# ----------------------------------------------------------------- derived composition
def test_an_unlisted_mapping_method_raises_instead_of_defaulting(rep):
    """The regression test for the whole workstream: a new source must not be able to slip an
    unclassified component into the corpus behind a default."""
    r = rec("x", {"source_type": "standard", "citation": "c", "doi": "", "url": ""},
            [comp("a_method_nobody_classified")])
    with pytest.raises(StageError) as e:
        S20.transform(r, rep)
    assert "component_evidence_classes.tsv" in str(e.value)


def test_a_fully_invented_medium_reports_zero_sourced_components(rep):
    r = rec("mediadive_1", dict(MEDIADIVE,
                                citation="DSMZ MediaDive (...); DSMZ Medium 1: NUTRIENT AGAR.",
                                url="https://www.dsmz.de/x.pdf"),
            [comp("hydrolysate_approximation") for _ in range(35)]
            + [comp("complex_decomposition", derived_from="Meat extract") for _ in range(10)]
            + [comp("base") for _ in range(4)],
            uncovered=["Agar"], pct=98.0)
    S20.transform(r, rep)
    cp = r["provenance"]["composition_provenance"]
    assert (cp["n_sourced"], cp["n_derived"], cp["pct_sourced_of_components"]) == (0, 49, 0.0)
    assert all(c["evidence_class"] == "derived" for c in r["components"])

    block = S39.coverage_for(r)
    assert block["pct_covered_all"] == 98.0      # the shipped number reproduces
    assert block["pct_covered_source"] == 0.0    # and the honest one is zero
    assert block["pct_covered_source_is_upper_bound"] is True
    assert block["replaced_ingredient_names_unavailable"] is True


def test_coverage_stage_refuses_an_unstamped_corpus():
    r = rec("x", {"source_type": "standard", "citation": "c", "doi": "", "url": ""},
            [comp("name")])
    with pytest.raises(StageError) as e:
        S39.coverage_for(r)          # evidence_class was never written
    assert "20_stamp_provenance" in str(e.value)


def test_a_zero_denominator_yields_null_and_never_a_flattering_default():
    r = rec("empty", {"source_type": "standard", "citation": "c", "doi": "", "url": ""},
            [], pct=None)
    block = S39.coverage_for(r)
    assert block["pct_covered_all"] is None
    assert block["pct_covered_source"] is None
    assert block["pct_sourced_of_components"] is None


def test_the_honest_number_can_never_exceed_the_advertised_one(rep):
    """Whatever the composition, source coverage is bounded above by legacy coverage — the
    property the stage asserts over the whole corpus."""
    for comps, unc in (
        ([comp("name")], []),
        ([comp("name"), comp("mineral_base")], ["thing"]),
        ([comp("hydrolysate_approximation")], []),
        ([comp("complex_decomposition", derived_from="yeast extract"), comp("name")], ["a", "b"]),
    ):
        r = rec("t", {"source_type": "standard", "citation": "c", "doi": "", "url": ""},
                comps, uncovered=unc)
        S20.transform(r, rep)
        b = S39.coverage_for(r)
        assert b["pct_covered_source"] <= b["pct_covered_all"] + 1e-9


# ----------------------------------------------------------------- corpus spot-check
def test_every_record_in_the_corpus_resolves_to_a_verified_source(stream, corpus_ids):
    seen, unresolved = 0, []
    for mid, r in stream():
        seen += 1
        if not resolve(r.get("provenance", {})).source_id:
            unresolved.append(mid)
    # a stream that yielded nothing would pass the assertion below trivially
    assert seen == len(corpus_ids) > 0, "streamed %d of %d records" % (seen, len(corpus_ids))
    assert unresolved == [], (
        "%d of %d records could not be resolved from their own provenance evidence: %s"
        % (len(unresolved), len(corpus_ids), unresolved[:10]))
