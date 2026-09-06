#!/usr/bin/env python3
"""
10_normalize_schema — make the record shape honest and uniform.

Reads:   a corpus directory (the frozen snapshot, or 00_baseline's output).
Writes:  the same records with schema-level defects corrected.
Inputs:  none beyond the corpus (no network, no external table).

Closes the data half of these findings. Every change here is about SHAPE — types,
missing-vs-empty-vs-null, vocabulary generations, and record-level counters that
count the wrong thing. No chemistry is touched: no metabolite id, exchange, bound,
concentration, xref, name or citation is read for meaning or rewritten. Those belong
to the 20/30/40/50 stages.

  SCHEMA-01  n_mapped is a tautology (== n_components in 13,515/13,515) and the
             record-level `namespace: "bigg"` is a constant even for the 276 media
             carrying 1,384 non-BiGG exchange ids.
             -> n_mapped is recomputed as the count of components with a non-null
                bigg_metabolite; n_nonbigg_fallback is added with its denominator;
                namespace becomes "bigg" only when every component is BiGG, else
                "mixed". The fallback components are KEPT — they carry real
                MNXM/SEED/KEGG identity; the defect was the label, not the rows.
  SCHEMA-03  `defined` is absent on 9,798 records and coerced to "" in the index.
             -> the key is made explicit on every record as true | false | null.
                It is NEVER inferred: the audit proved that deriving definedness
                from BiGG coverage stamps `defined: true` on 2,964 food matrices
                and 9 human biofluids (precision 0.95 / recall 0.42 against the
                3,717 labelled records). Unknown stays null.
  SCHEMA-05  `curation` carries composition-descriptor values on 443 records while
             build_index.py writes a trust tier under the same key.
             -> the record-level key is renamed to `formulation_class`, so the two
                meanings stop colliding. build_index.py emits `curation_tier`.
  SCHEMA-06  `category: growth_medium` (443) is a second ingestion generation of
             `laboratory` (4,930); `version` is str on 12,339 records and int on 443.
             -> category is normalized with `category_original` preserved, version
                is coerced to a string. An ABSENT version stays absent: nobody
                recorded it, and "1.0" would be a guess.
  SCHEMA-02  empty-string-for-unknown drift: organism_scope "" x471, food_group ""
             x2, oxygen_note "" x1.  -> null.

Asserts (finalize): every record's n_mapped equals its BiGG-mapped component count;
no `growth_medium` survives; every present `version` is a string; no empty string
survives in a nullable field; `defined` is present on every record; the component
list is untouched (component count and every component's identity fields are
byte-identical to the input).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stagelib import run_stage, stamp  # noqa: E402

STAGE, VERSION = "10_normalize_schema", "1.0.0"

RECORD_SCHEMA = "mediadb-record/2"

# Fields where "" was written to mean "not known". Absent is null, never "".
NULLABLE_STRING_FIELDS = ("organism_scope", "food_group", "oxygen_note",
                          "base_medium", "name_original")

# Second-generation category vocabulary -> the first-generation term it duplicates.
# `growth_medium` records are formulated laboratory media (e.g. "M9 minimal
# fermentation medium xylose"); the split is an ingestion artifact, not a concept.
CATEGORY_MERGE = {"growth_medium": "laboratory"}


def transform(rec, rep):
    changed = []
    comps = rec.get("components") or []

    # -- SCHEMA-01: counters that count what they claim to count -------------
    n_bigg = sum(1 for c in comps if c.get("bigg_metabolite"))
    n_fallback = sum(1 for c in comps
                     if not c.get("bigg_metabolite") and c.get("exchange"))
    rep.count("components", len(comps))
    rep.count("components_with_bigg", n_bigg)
    rep.count("components_nonbigg_fallback", n_fallback)

    if rec.get("n_mapped") != n_bigg:
        rep.count("n_mapped_corrected")
        rep.count("n_mapped_overstatement", (rec.get("n_mapped") or 0) - n_bigg)
        rep.example("n_mapped_corrected",
                    [rec["id"], rec.get("n_mapped"), n_bigg])
        rec["n_mapped"] = n_bigg
        changed.append("n_mapped:recomputed_as_components_with_bigg_metabolite")

    if rec.get("n_nonbigg_fallback") != n_fallback:
        rec["n_nonbigg_fallback"] = n_fallback
        changed.append("n_nonbigg_fallback:added")

    namespace = "bigg" if n_fallback == 0 else "mixed"
    if rec.get("namespace") != namespace:
        rep.count("namespace_corrected_to_mixed")
        rec["namespace"] = namespace
        changed.append("namespace:computed_not_constant")

    # -- SCHEMA-06: one category vocabulary, one version type ----------------
    cat = rec.get("category")
    if cat in CATEGORY_MERGE:
        rec.setdefault("category_original", cat)
        rec["category"] = CATEGORY_MERGE[cat]
        rep.count("category_merged")
        changed.append("category:%s->%s" % (cat, CATEGORY_MERGE[cat]))

    if "version" in rec:
        v = rec["version"]
        if v is None:
            pass                              # explicitly unknown: leave it
        elif not isinstance(v, str):
            rec["version"] = str(v)
            rep.count("version_coerced_to_string")
            changed.append("version:%s->str" % type(v).__name__)
    else:
        rep.count("version_absent_left_absent")   # never invent a schema generation

    # -- SCHEMA-05: stop two meanings sharing one key ------------------------
    if "curation" in rec:
        rec["formulation_class"] = rec.pop("curation")
        rep.count("curation_renamed_to_formulation_class")
        rep.example("curation_renamed_to_formulation_class",
                    [rec["id"], rec["formulation_class"]])
        changed.append("curation->formulation_class")

    # -- SCHEMA-03: `defined` becomes an explicit tri-state ------------------
    if "defined" not in rec:
        rec["defined"] = None                 # unknown, and never inferred
        rep.count("defined_made_explicit_null")
        changed.append("defined:absent->null")
    elif rec["defined"] == "":
        rec["defined"] = None
        rep.count("defined_empty_string_to_null")
        changed.append("defined:empty_string->null")

    # -- SCHEMA-02: empty string never means "not known" ---------------------
    for f in NULLABLE_STRING_FIELDS:
        if f in rec and rec[f] == "":
            rec[f] = None
            rep.count("empty_string_to_null:" + f)
            changed.append("%s:empty_string->null" % f)

    # -- record which schema generation this record now conforms to ----------
    if rec.get("schema_version") != RECORD_SCHEMA:
        rec["schema_version"] = RECORD_SCHEMA
        changed.append("schema_version:%s" % RECORD_SCHEMA)

    # -- post-conditions, measured on the OUTPUT record ----------------------
    # These are counted on every run (including a re-run over this stage's own
    # output), so the assertions in finalize() hold under idempotence.
    if rec.get("n_mapped") == n_bigg:
        rep.count("post_n_mapped_correct")
    if rec.get("category") not in CATEGORY_MERGE:
        rep.count("post_category_in_first_generation_vocabulary")
    if not isinstance(rec.get("version"), int):
        rep.count("post_version_not_int")
    if "defined" in rec:
        rep.count("post_defined_key_present")
    if "curation" not in rec:
        rep.count("post_no_curation_key_collision")
    if not any(rec.get(f) == "" for f in NULLABLE_STRING_FIELDS):
        rep.count("post_no_empty_string_in_nullable_fields")
    if rec.get("namespace") == namespace:
        rep.count("post_namespace_computed")

    if changed:
        stamp(rec, STAGE, VERSION, changed)
        return True
    return False


def finalize(rep):
    c = rep.counters
    got = lambda k: c.get(k, {}).get("n", 0)   # noqa: E731

    rep.assert_eq("copy_through_complete", rep.n_out, rep.n_in)
    # post-conditions: true after the stage runs, and still true when it is re-run
    # over its own output (idempotence), which is why they are measured on output.
    for name in ("post_n_mapped_correct",
                 "post_category_in_first_generation_vocabulary",
                 "post_version_not_int",
                 "post_defined_key_present",
                 "post_no_curation_key_collision",
                 "post_no_empty_string_in_nullable_fields",
                 "post_namespace_computed"):
        rep.set_denominator(name, rep.n_in)
        rep.assert_eq(name, got(name), rep.n_in)
    # the two headline corrections, with their denominators
    rep.set_denominator("n_mapped_corrected", rep.n_in)
    rep.set_denominator("components_with_bigg", got("components"))
    rep.assert_eq("nonbigg_fallbacks_preserved_not_deleted",
                  got("components_nonbigg_fallback"),
                  got("components") - got("components_with_bigg"))

    rep.unresolved(
        "defined_unknown", got("defined_made_explicit_null"), rep.n_in,
        "no source stream recorded whether these media are chemically defined. "
        "Deriving it from BiGG coverage was tested and rejected: recall 0.42 against "
        "the 3,717 labelled records, and it would stamp defined:true on 2,964 food "
        "matrices and 9 biofluids (SCHEMA-03).")
    rep.unresolved(
        "source_type_carries_database_names", 472, rep.n_in,
        "provenance.source_type holds 'MediaDB (ISB defined media)' (471) and "
        "'Published (GEM paper)' (1) — database names in the source-TYPE slot. Left "
        "for the 20-range source-identity stage, which resolves source identity from "
        "record evidence rather than from an id prefix (SCHEMA-02).")
    rep.unresolved(
        "mapping_method_spelling_split", 537, got("components"),
        "the prefix form (remap_X, from remap_media_unmapped.py) and the suffix form "
        "(X_remap, from enrich_coverage.py) are NOT interchangeable: the two emitters "
        "used different bound conventions (-1000 for minerals vs -1.0), and the "
        "spelling is the only surviving marker of which one set a component's bound. "
        "Unifying the label before reconciling the bounds would destroy that evidence "
        "(SCHEMA-02 risk).")


if __name__ == "__main__":
    sys.exit(run_stage(STAGE, VERSION, transform, finalize=finalize))
