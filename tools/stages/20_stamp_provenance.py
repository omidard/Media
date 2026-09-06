#!/usr/bin/env python3
"""Stage 20 — licence, verified source identity, and honest provenance labels.

READS  a corpus directory, plus three checked-in tables:
         tools/licenses.tsv                    per-source licence schedule (the authority
                                               for every licence claim this stage makes)
         tools/component_evidence_classes.tsv  sourced/derived class of every mapping_method
         tools/verification_verdicts.tsv       the earlier verification pass's verdicts
WRITES the same corpus with, per record, a resolved source identity, its upstream licence
       and commercial-use flag, the true culture collection behind MediaDive, an explicit
       citation type, an honest verification status, and, per component, whether it was read
       from the source or supplied by the pipeline.

CLOSES PROV-05 (blanket CC-BY-4.0 over CC BY-NC and All-Rights-Reserved content),
       PROV-01 / PROV-06 / PROV-11 / PROV-16 (what the citation actually identifies, and the
       1,248 media named and cited as DSMZ that belong to JCM or CCAP),
       PROV-03 (media the verification pass rejected still labelled "paper-verified"),
       and the labelling half of PROV-07 / COV-03 / MEDIA-WEB-02 (derived-not-sourced
       components). Stage 39 turns that labelling into an honest coverage number.

ASSERTS
  every record resolves to a source in the closed vocabulary (0 guessed, 0 unresolved);
  every mapping_method observed has a row in the classification table (no default, ever);
  no record leaves this stage claiming "paper-verified" against a contradicting verdict
  or its own contradicting note;
  no emitted citation asserts DSMZ for a medium of another collection;
  commercial_use_ok is true only where the schedule says commercial_use == "yes";
  every stamped licence carries the URL its terms were read from and the date.

DOES NOT delete a record, delete a component, rename a medium, or invent an identifier.
       The operator's decision is segregate and label. The 1,189 non-commercial and
       all-rights-reserved records stay; the 229,486 pipeline-derived components stay; the
       9 mislabelled media are relabelled, not quarantined, because the recuration rounds
       that followed the verdicts did real source-chasing and the recipes are largely right.
       Display names still saying "DSMZ" are flagged in provenance.attribution_conflict with
       a suggested name for the naming stage (50-59) rather than renamed here.

WHY IDENTITY IS NOT TAKEN FROM THE ID
       build_index.py:source_db() infers the source from `idv.startswith('mediadive_')`.
       That inference already mis-attributes 5 DSMZ-citing records and files 5 bovine BMDB
       records as human HMDB-derived. A licence stamped off a filename is a legal assertion
       built on a string match. tools/source_identity.py resolves identity from evidence
       inside the record — URL host, DOI, citation text — and returns that evidence with the
       answer. Contract rule 5 (never key on an id prefix for a provenance claim).
"""

from __future__ import annotations

import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)

from stagelib import REPO, Report, StageError, main_guard, stamp  # noqa: E402
from source_identity import SOURCE_IDS, resolve                   # noqa: E402

STAGE, VERSION = "20_stamp_provenance", "1.0.0"

LICENSES_TSV = os.path.join(TOOLS, "licenses.tsv")
EVIDENCE_TSV = os.path.join(TOOLS, "component_evidence_classes.tsv")
VERDICTS_TSV = os.path.join(TOOLS, "verification_verdicts.tsv")

# Re-verified 2026-09-06 by curl and by headless Chromium. Audit finding PROV-02 claimed
# these links were dead; its verification pass refuted that, and so did this session: curl
# returns HTTP 404 with an identical 52,480-byte application shell for every id, while
# headless Chromium loads the same URL and renders the correct food page (1104705 ->
# "Flour, soy, defatted - Nutrients - Foundation | USDA FoodData Central"). It is a USDA
# server-side soft-404. Retiring a working link would be the over-correction; it is annotated
# instead, so a link-checker knows the status code is lying.
USDA_URL_STATUS = "soft_404"
USDA_URL_NOTE = (
    "USDA FoodData Central returns HTTP 404 for food-details URLs while its single-page app "
    "renders the correct food page client-side (verified 2026-09-06: curl -> 404 with an "
    "identical app shell for every id; headless Chromium -> the correct title and nutrient "
    "table). The link works for a reader and fails for a link-checker. Do not retire it."
)

CITATION_TYPE_BY_SOURCE = {
    "usda_fdc": "database_record",
    "foodb": "database_record",
    "mediadb_isb": "database_record",
    "hmdb": "database_record",
    "bmdb": "database_record",
    "dsmz_mediadive": "collection_catalog",
    "growthdb_literature": "primary_paper",
    "primary_literature": "primary_paper",
    "hmdb_via_publication": "primary_paper",
    "standard_classic": "classic_reference",
}

_MEDIADIVE_NAME_RE = re.compile(r"DSMZ Medium\s+[A-Za-z]?\d+[a-z]?:\s*(.+?)\.?\s*$")


# --------------------------------------------------------------------------- tables
def _read_tsv(path):
    if not os.path.exists(path):
        raise StageError("required table missing: %s" % path)
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def load_licenses(path=LICENSES_TSV):
    rows = {}
    for r in _read_tsv(path):
        sid = r["source_id"].strip()
        if sid in rows:
            raise StageError("duplicate source_id %r in %s" % (sid, path))
        rows[sid] = r
    unknown = set(rows) - set(SOURCE_IDS)
    missing = set(SOURCE_IDS) - set(rows)
    if unknown or missing:
        raise StageError(
            "licence schedule and source vocabulary disagree: only in TSV %s, only in "
            "source_identity %s" % (sorted(unknown), sorted(missing)))
    for sid, r in rows.items():
        if (r["commercial_use_ok"].strip().lower() == "true") != (r["commercial_use"].strip() == "yes"):
            raise StageError(
                "%s: commercial_use_ok must be true only where commercial_use == 'yes' "
                "(got %r / %r)" % (sid, r["commercial_use"], r["commercial_use_ok"]))
        if not r["terms_retrieved"].strip():
            raise StageError("%s: licence row carries no terms_retrieved date" % sid)
        if not r["terms_url"].strip() and r["terms_verification"] != "project_assertion":
            raise StageError("%s: licence row carries no terms_url" % sid)
    return rows


def load_evidence_classes(path=EVIDENCE_TSV):
    return {r["mapping_method"].strip(): r for r in _read_tsv(path)}


def load_verdicts(path=VERDICTS_TSV):
    return {r["medium_id"].strip(): r for r in _read_tsv(path)}


LICENSES = load_licenses()
EVIDENCE = load_evidence_classes()
VERDICTS = load_verdicts()


# --------------------------------------------------------------------------- helpers
def citation_facts(prov, ident):
    """(citation_type, has_primary_citation, citation_resolved).

    citation_type says what the cited thing IS: primary_paper | collection_catalog |
    database_record | classic_reference | none. "Every medium carries a citation" is true as
    a string test and false as a provenance claim — 89.2% of these citations identify a
    database record or an aggregator, not a work containing the formulation (PROV-01).

    has_primary_citation is deliberately not derived from the `doi` field: 1,456 literature
    records leave `doi` empty and carry their PMC id in the URL, which is why a doi-field
    census reports 236 distinct works where the union is about 1,070.

    citation_resolved asks the harder question — can a machine turn this citation into a
    specific work? For the 459 author-year stubs ("Lovley dr et al, 1993" x56) the honest
    answer is false, not a Crossref guess (PROV-16).
    """
    ctype = CITATION_TYPE_BY_SOURCE.get(ident.source_id)
    if not (prov.get("citation") or "").strip():
        ctype = "none"
    return ctype, ctype == "primary_paper", bool(ident.primary_identifier or prov.get("pmid"))


def rebuild_mediadive_citation(prov, ident):
    """Name the true collection, with MediaDive as what it is: the aggregator.

    All 3,148 MediaDive records assert "DSMZ Medium <n>", including the 1,248 that belong to
    JCM or CCAP (PROV-06, NM-03). MediaDive's own imprint says "JCM media were kindly
    provided by the JCM", and the DSMZ recipe PDF for a JCM medium returns 404.

    The collection's own medium id appears only where it is verifiable: as MediaDive states
    it for DSMZ, and for JCM only when confirmed against the RIKEN GRMD number in the URL.
    CCAP publishes filename-based recipe PDFs with no visible numeric id, so its id stays
    null and the citation falls back to the MediaDive-namespaced number. An absent value is
    null, never a guess.
    """
    m = _MEDIADIVE_NAME_RE.search(prov.get("citation") or "")
    name = m.group(1).strip().rstrip(".") if m else ""
    coll = ident.collection or "an unidentified collection"
    if ident.collection_medium_id:
        ref = "%s medium %s" % (coll, ident.collection_medium_id)
    elif ident.mediadive_number:
        ref = "%s medium (MediaDive %s)" % (coll, ident.mediadive_number)
    else:
        ref = "%s medium" % coll
    return "MediaDive (Koblitz J et al., Nucleic Acids Res 2023), aggregating %s%s" % (
        ref, (": %s." % name) if name else ".")


def verification_facts(mid, prov):
    """(status, downgrade_reason or None).

    The contradiction alarm: a record must not simultaneously say "paper-verified" and carry
    a note explaining that the cited paper does not contain the recipe. It fires on exactly
    the records the project's own verification pass rejected, and it is self-maintaining —
    any future record that acquires both trips it.

    Downgrading is the whole fix. These records are NOT quarantined: the recuration rounds
    that followed the verdicts traced the V4 base to Dunfield 2007 and recovered SMM from a
    dissertation, so the recipes are largely right and better sourced than the verdict that
    condemned them. What is false is the label (PROV-03).
    """
    raw = prov.get("verification")
    note = prov.get("verification_note")
    verdict = VERDICTS.get(mid, {}).get("verdict")

    if not raw:
        status = "unverified"
    elif str(raw).startswith("paper-verified"):
        status = "paper-verified"
    elif str(raw).startswith("expert-curated"):
        status = "expert-curated"
    elif str(raw).startswith("reference-database"):
        status = "reference-database"
    elif str(raw).startswith("auto-extracted"):
        status = "auto-extracted"
    else:
        status = "other"

    if status == "paper-verified" and (note or verdict in ("unavailable", "not_found")):
        bits = []
        if verdict:
            bits.append("the project's verification pass recorded verdict %r "
                        "(tools/verification_verdicts.tsv)" % verdict)
        if note:
            bits.append("the record's own provenance.verification_note contradicts the label")
        return "reconstructed-from-cited-references", (
            "Downgraded from %r: %s. The cited work does not contain this formulation; the "
            "recipe was reconstructed from references chased out of it." % (raw, "; and ".join(bits)))
    if status == "unverified" and verdict in ("unavailable", "not_found"):
        return "rejected-by-verification-pass", (
            "The project's verification pass recorded verdict %r and the record carries no "
            "verification field at all." % verdict)
    return status, None


# --------------------------------------------------------------------------- the transform
def transform(rec, rep):
    changed = []
    mid = rec.get("id")
    prov = rec.setdefault("provenance", {})

    def put(key, value):
        if prov.get(key) != value or key not in prov:
            prov[key] = value
            changed.append("provenance.%s" % key)

    # Resolve against the ORIGINAL citation whenever this stage has already rewritten one, so
    # every derived value stays a pure function of the input the pipeline first saw. That is
    # what makes the stage idempotent instead of re-parsing its own prose (contract rule 6).
    prov_view = dict(prov)
    if prov.get("citation_original"):
        prov_view["citation"] = prov["citation_original"]

    ident = resolve(prov_view)
    if not ident.source_id:
        raise StageError(
            "%s: source identity unresolved from provenance evidence (url=%r doi=%r "
            "source_type=%r). A stage never guesses a source into a bucket — add an "
            "evidence rule to tools/source_identity.py instead."
            % (mid, prov.get("url"), prov.get("doi"), prov.get("source_type")))
    lic = LICENSES[ident.source_id]

    rep.count("source_resolved", 1, rep.n_in)
    rep.count("source_%s" % ident.source_id, 1)

    put("source_id", ident.source_id)
    put("source_name", ident.source_name)
    put("source_identity_evidence", ident.evidence)
    put("source_identity_confidence", ident.confidence)

    put("license", lic["license_id"])
    put("license_name", lic["license_name"])
    put("license_url", lic["license_url"] or None)
    put("license_source", lic["source_name"])
    put("license_terms_url", lic["terms_url"] or None)
    put("license_terms_retrieved", lic["terms_retrieved"] or None)
    put("license_terms_verification", lic["terms_verification"])
    put("commercial_use", lic["commercial_use"])
    put("commercial_use_ok", lic["commercial_use_ok"].strip().lower() == "true")
    put("attribution_required", lic["attribution_required"].strip().lower() == "true")
    put("license_indication_required", lic["license_indication_required"].strip().lower() == "true")
    rep.count("license_%s" % lic["license_id"], 1)
    rep.count("commercial_use_%s" % lic["commercial_use"], 1, rep.n_in)

    review = [f for f in ident.flags if f.startswith("license_review_required")]
    if ident.source_id == "hmdb_via_publication":
        review.append("license_review_required:underlying_values_are_HMDB_CC-BY-NC_"
                      "republished_in_a_CC-BY_paper")
    put("license_review_required", bool(review))
    put("license_review_reason", "; ".join(review) if review else None)
    if review:
        rep.count("license_review_required", 1, rep.n_in)
        rep.example("license_review_required", {"id": mid, "why": review[0]})

    # --- the true culture collection, and the citation that names it ----------------------
    if ident.source_id == "dsmz_mediadive":
        put("collection", ident.collection)
        put("collection_evidence", ident.collection_evidence)
        put("collection_medium_id", ident.collection_medium_id)
        put("aggregator", "MediaDive (DSMZ)")
        rep.count("mediadive_collection_%s" % (ident.collection or "unresolved"), 1)
        if ident.collection_medium_id is None:
            rep.count("collection_medium_id_null_not_guessed", 1)

        new_cite = rebuild_mediadive_citation(prov_view, ident)
        if new_cite != prov.get("citation"):
            if "citation_original" not in prov:
                prov["citation_original"] = prov_view.get("citation")
                changed.append("provenance.citation_original")
            prov["citation"] = new_cite
            changed.append("provenance.citation")
            rep.count("citation_rewritten", 1)

        if ident.collection and ident.collection != "DSMZ":
            rep.count("citation_dsmz_misattribution_corrected", 1, rep.n_in)
            display = rec.get("name") or ""
            suggested = None
            if ident.mediadive_number:
                ref = ("%s %s, via MediaDive" % (ident.collection, ident.collection_medium_id)
                       if ident.collection_medium_id
                       else "%s, via MediaDive %s" % (ident.collection, ident.mediadive_number))
                cand = re.sub(r"\(DSMZ\s+%s\)" % re.escape(ident.mediadive_number),
                              "(%s)" % ref, display)
                suggested = cand if cand != display else None
            put("attribution_conflict", {
                "field": "name",
                "asserts": "DSMZ",
                "true_collection": ident.collection,
                "evidence": ident.collection_evidence,
                "suggested_name": suggested,
                "note": ("The display name still says DSMZ. It is left unchanged here so this "
                         "stage does not collide with the naming stage (range 50-59), which "
                         "should apply suggested_name."),
            })
            rep.example("attribution_conflict",
                        {"id": mid, "name": display, "true_collection": ident.collection})

    if ident.source_id == "usda_fdc":
        put("url_status", USDA_URL_STATUS)
        put("url_status_note", USDA_URL_NOTE)

    # --- what the citation actually identifies ---------------------------------------------
    ctype, has_primary, resolved = citation_facts(prov, ident)
    put("citation_type", ctype)
    put("has_primary_citation", has_primary)
    put("citation_resolved", resolved)
    put("primary_identifier", ident.primary_identifier)
    rep.count("citation_type_%s" % ctype, 1, rep.n_in)
    if not resolved:
        rep.count("citation_not_machine_resolvable", 1, rep.n_in)

    # --- verification status ----------------------------------------------------------------
    status, reason = verification_facts(mid, prov)
    if reason and prov.get("verification") and "verification_original" not in prov:
        prov["verification_original"] = prov["verification"]
        changed.append("provenance.verification_original")
    put("verification_status", status)
    put("verification_downgrade_reason", reason)
    vrow = VERDICTS.get(mid)
    if vrow:
        put("verification_pass_verdict", {
            "verdict": vrow["verdict"],
            "confidence": vrow["verdict_confidence"] or None,
            "source": "tools/verification_verdicts.tsv",
        })
    rep.count("verification_%s" % status, 1, rep.n_in)
    if status == "paper-verified" and (
        prov.get("verification_note") or VERDICTS.get(mid, {}).get("verdict") in ("unavailable", "not_found")
    ):
        # Must be unreachable: verification_facts downgrades exactly this case. Counted so
        # the assertion tests the corpus rather than restating the code.
        rep.count("verification_paper_verified_still_contradicted", 1, rep.n_in)
    if reason:
        rep.count("verification_downgraded", 1, rep.n_in)
        rep.example("verification_downgraded",
                    {"id": mid, "was": prov.get("verification_original"), "now": status,
                     "n_components": len(rec.get("components", []))})

    # --- sourced vs derived, per component ---------------------------------------------------
    n_sourced = n_inf = n_inj = n_base = 0
    for c in rec.get("components", []):
        m = c.get("mapping_method")
        row = EVIDENCE.get(m)
        if row is None:
            raise StageError(
                "%s: mapping_method %r has no row in tools/component_evidence_classes.tsv. "
                "A component's evidence class is never defaulted — add the method to the "
                "table with its class, or the corpus ships an unclassified component." % (mid, m))
        ec = row["evidence_class"]
        dc = row["derived_class"] or None
        if c.get("evidence_class") != ec:
            c["evidence_class"] = ec
            changed.append("components[].evidence_class")
        if c.get("derived_class") != dc or "derived_class" not in c:
            c["derived_class"] = dc
            changed.append("components[].derived_class")
        if ec == "sourced":
            n_sourced += 1
        elif dc == "inferred_from_listed_ingredient":
            n_inf += 1
        elif dc == "injected_convention":
            n_inj += 1
        elif dc == "canonical_base_expansion":
            n_base += 1

    n_total = len(rec.get("components", []))
    n_derived = n_inf + n_inj + n_base
    rep.count("components_total", n_total)
    rep.count("components_sourced", n_sourced)
    rep.count("components_derived", n_derived)
    rep.count("components_derived_inferred", n_inf)
    rep.count("components_derived_injected", n_inj)
    rep.count("components_derived_canonical_base", n_base)
    if n_total and n_sourced == 0:
        rep.count("media_with_no_sourced_component", 1, rep.n_in)
        rep.example("media_with_no_sourced_component", {"id": mid, "n_components": n_total})

    put("composition_provenance", {
        "n_components": n_total,
        "n_sourced": n_sourced,
        "n_derived": n_derived,
        "n_derived_inferred_from_listed_ingredient": n_inf,
        "n_derived_injected_convention": n_inj,
        "n_derived_canonical_base_expansion": n_base,
        "pct_sourced_of_components": (round(100.0 * n_sourced / n_total, 1) if n_total else None),
        "definition": ("sourced = the cited source states this component; derived = the "
                       "pipeline supplied it. Classification table: "
                       "tools/component_evidence_classes.tsv."),
    })

    if changed:
        stamp(rec, STAGE, VERSION, changed)
        return True
    return False


def finalize(rep):
    n = rep.n_in
    c = rep.counters

    def got(name):
        return c.get(name, {"n": 0})["n"]

    rep.assert_eq("every_record_resolved_to_a_verified_source", got("source_resolved"), n)
    rep.assert_eq(
        "licence_classes_partition_the_corpus",
        sum(v["n"] for k, v in c.items() if k.startswith("license_")
            and k != "license_review_required"),
        n)
    rep.assert_eq(
        "commercial_use_flags_partition_the_corpus",
        sum(v["n"] for k, v in c.items() if k.startswith("commercial_use_")), n)
    rep.assert_eq(
        "citation_types_partition_the_corpus",
        sum(v["n"] for k, v in c.items() if k.startswith("citation_type_")), n)
    rep.assert_eq(
        "components_partition_into_sourced_and_derived",
        got("components_sourced") + got("components_derived"), got("components_total"))
    # A downgrade lands in exactly one of two statuses, and nowhere else: a record that
    # claimed "paper-verified" against a contradicting verdict or note becomes
    # `reconstructed-from-cited-references`, and a record the pass rejected that never
    # carried a label at all becomes `rejected-by-verification-pass`. Asserting the sum
    # rather than one term is what makes this a real check — the first version of this
    # assertion compared the total against one term and failed on the full corpus.
    rep.assert_eq(
        "every_downgrade_lands_in_a_downgrade_status",
        got("verification_downgraded"),
        got("verification_reconstructed-from-cited-references")
        + got("verification_rejected-by-verification-pass"))
    rep.assert_eq(
        "no_record_left_claiming_paper_verified_against_a_contradicting_verdict",
        got("verification_paper_verified_still_contradicted"), 0)

    # What this stage could NOT determine, stated rather than filled in.
    rep.unresolved(
        "citation_not_machine_resolvable", got("citation_not_machine_resolvable"), n,
        "the citation carries no DOI, PMID or PMC id — mostly MediaDB author-year stubs. "
        "Resolving 'Park et al, 2004' against Crossref would turn a visible gap into an "
        "invisible fabrication, so these stay null.")
    rep.unresolved(
        "license_review_required", got("license_review_required"), n,
        "the record's composition may derive from a source with different terms than the "
        "one its provenance names; flagged rather than silently assigned.")
    rep.unresolved(
        "collection_medium_id_null", got("collection_medium_id_null_not_guessed"), n,
        "CCAP publishes filename-based recipe PDFs with no visible numeric medium id, so the "
        "originating collection's own id cannot be asserted for those records.")
    rep.unresolved(
        "media_still_displaying_a_wrong_collection_in_their_name",
        got("citation_dsmz_misattribution_corrected"), n,
        "the citation is corrected here; the display name is left to the naming stage "
        "(range 50-59), which receives a suggested_name in provenance.attribution_conflict.")


if __name__ == "__main__":
    main_guard(STAGE, VERSION, transform, finalize=finalize,
               inputs=["tools/licenses.tsv", "tools/component_evidence_classes.tsv",
                       "tools/verification_verdicts.tsv", "tools/source_identity.py"])
