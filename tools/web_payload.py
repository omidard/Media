#!/usr/bin/env python3
"""Project the corrected corpus into the payload the browser reads.

FINDINGS: MEDIA-WEB-01 MEDIA-WEB-02 MEDIA-WEB-04 MEDIA-WEB-05 MEDIA-WEB-06
MEDIA-WEB-07 MEDIA-WEB-10 MEDIA-WEB-11 MEDIA-WEB-14 MEDIA-WEB-16 MEDIA-WEB-17
MEDIA-WEB-18 MEDIA-WEB-20 UX-01 COV-02 COV-05 NM-05

WHAT THIS IS
------------
`data/media/*.json` is the sole surviving copy of the corpus and it is large:
1.4 GB across 13,515 records, and `data/index.json` (the documented API catalog)
is 16.7 MB. Neither is a thing to hand a browser. This module projects the
corpus into five small artifacts under `data/web/`, each of which carries the
denominator of every count it states:

  catalog.json     one row per medium, dictionary-encoded, plus the library-wide
                   aggregates the pages render. No page computes a headline
                   number from a filtered subset.
  compounds.json   the complete exchange -> media inverted index (every one of
                   the 1,793 exchanges, not the 77 of the stale presence matrix),
                   plus a compound dictionary carrying InChIKey / KEGG / ChEBI /
                   formula so a compound can be found by chemistry and not only
                   by name. Loaded lazily, on the first compound query.
  families.json    base-medium families with their variants and what differs
                   between them, so "browse LB" is a navigation concept rather
                   than 33 unrelated rows.
  tombstones.json  the 77 media the verification pass assessed and withdrew,
                   with the reason, so a rotted `?medium=` permalink says what
                   happened instead of rendering an ordinary landing page.
  twins.json       the groups of media that hand a model the identical constraint
                   set. Half this library is degenerate as a model input, and a
                   reader choosing between two media is entitled to know when the
                   choice makes no difference to a solver.

WHAT IT REFUSES TO DO
---------------------
* It never coerces an absent measurement to a number. `pct_covered_source` is
  null when its denominator was zero, and the browser renders null as "not
  computed", never as 100%.
* It never derives a display value from an id prefix or a filename.
* Every aggregate it writes carries `_of` (the denominator) beside it.
* It asserts its own totals against the corpus it read and raises on a mismatch,
  so a payload can never ship a total the corpus does not support.
"""
from __future__ import annotations

import datetime as dt
import glob
import gzip
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model_input import Degeneracy   # noqa: E402
import refs as R                     # noqa: E402

SCHEMA = "mediadb-web-payload/1"

# --------------------------------------------------------------------------
# The evidence spine.
#
# `evidence_tier` (written by the chemistry stage) records how each component's
# identity was ACTUALLY decided. The browser groups the twelve tiers into six
# classes so a reader can tell, at the moment they decide whether to trust a
# component, whether it was resolved by structure, by an identifier, by a name
# string, by a class assumption, or invented by the pipeline. This ordering is
# the trust ordering: index 0 is the strongest evidence, index 5 the weakest.
# It is the single definition of the vocabulary; the CSS, the legend and the
# methods page all read it from the payload rather than restating it.
# --------------------------------------------------------------------------
EVIDENCE_CLASSES = [
    {
        "id": "structure",
        "label": "Structure-verified",
        "tiers": ["structural_xref"],
        "definition": (
            "A structural cross-reference carried by the source (InChIKey, "
            "formula) matched the structure of the BiGG metabolite it was "
            "mapped to. Identity was decided by chemistry."),
    },
    {
        "id": "identifier",
        "label": "Identifier-verified",
        "tiers": ["source_bigg_id", "curated_mapping"],
        "definition": (
            "The source record supplied a database identifier, or a reviewed "
            "curation table named the target explicitly. Identity was decided "
            "by a cross-reference rather than by a name string."),
    },
    {
        "id": "name",
        "label": "Name-matched",
        "tiers": ["exact_name", "name_table", "fuzzy_name"],
        "definition": (
            "Identity was decided by matching a name string: an exact name, a "
            "hard-coded nutrient-name table, or a fuzzy match. No structure and "
            "no identifier was checked. A name match is a fallback tier, not a "
            "confirmation, and it is the single largest class in this library."),
    },
    {
        "id": "class_or_assertion",
        "label": "Class or assertion",
        "tiers": ["class_proxy", "author_asserted", "non_bigg_fallback"],
        "definition": (
            "Either a class label was collapsed onto one representative "
            "molecule (a vitamer group onto one vitamer, a fatty-acid class "
            "onto one isomer, an element onto one oxidation state), or the "
            "record's author asserted the component with no external "
            "identifier. The specific molecule is an assumption, not a "
            "measurement."),
    },
    {
        "id": "derived",
        "label": "Pipeline-derived",
        "tiers": ["derived_component"],
        "definition": (
            "The cited source never states this component. This pipeline "
            "supplied it, by decomposing a complex ingredient, approximating a "
            "hydrolysate, or injecting a standard mineral or oxygen base. It is "
            "an in-silico addition. It is kept because models need it to grow, "
            "labelled everywhere it appears, and excluded from every "
            "source-coverage number."),
    },
    {
        "id": "unresolved",
        "label": "Unresolved",
        "tiers": ["unmapped", "unmappable_mixture"],
        "definition": (
            "No identity was established, or the ingredient is an undefined "
            "mixture (yeast extract, peptone, a trace-element solution) that "
            "has no single molecular identity to establish."),
    },
]
TIER_TO_CLASS = {t: c["id"] for c in EVIDENCE_CLASSES for t in c["tiers"]}
CLASS_ORDER = [c["id"] for c in EVIDENCE_CLASSES]

# Columns of catalog.json `rows`, in order. Rows are arrays and the enum columns
# are dictionary-encoded (see `dicts`) purely to keep the payload small: the
# readable, documented catalog is data/index.json. Any consumer that wants
# objects can zip `columns` against a row.
COLUMNS = [
    "id", "name", "category", "source_db", "license", "commercial_use_ok",
    "verification_status", "oxygen", "organism_scope",
    "n_components", "n_sourced", "n_derived", "n_uncovered",
    "pct_covered_source", "pct_covered_source_is_upper_bound", "family",
    "n_with_concentration_mM", "food_group", "defined",
    # The two ways a component can fail to reach a BiGG exchange, per record. The
    # library-wide claim was "every component mapped to a BiGG exchange"; it is true
    # of 664,000 of 665,582 components and the exceptions were invisible per record.
    "n_nonbigg_fallback", "n_no_exchange",
    # How many OTHER records hand a model the identical constraint set (0 = unique).
    "model_input_twins",
] + ["ev_" + c for c in CLASS_ORDER]

ENUM_COLUMNS = ("category", "source_db", "license", "verification_status",
                "oxygen", "organism_scope", "family", "food_group")

COLUMN_NOTES = {
    "n_components": "components in the record. Most carry a BiGG exchange; "
                    "n_nonbigg_fallback and n_no_exchange say how many do not",
    "n_nonbigg_fallback": "of n_components, the number whose exchange id is a "
                           "ModelSEED/MetaNetX/KEGG fallback, not a BiGG id. No "
                           "BiGG model will accept it. 1,364 of 665,582 "
                           "components library-wide",
    "n_no_exchange": "of n_components, the number with no exchange reaction at "
                     "all: identity was never established, or the ingredient is "
                     "an undefined mixture. 218 of 665,582 library-wide",
    "model_input_twins": "how many OTHER records hand a model the identical set "
                         "of (exchange, lower bound, upper bound) triples. 0 "
                         "means this record's model input is unique in the "
                         "library; see model_input_degeneracy",
    "n_sourced": "of those, the number the cited source actually states",
    "n_derived": "of those, the number this pipeline supplied (see the "
                 "pipeline-derived evidence class)",
    "n_uncovered": "ingredients the source states that got no exchange at all; "
                   "they are NOT in n_components",
    "pct_covered_source": "share of the source's own ingredient list that "
                          "reached an exchange. null means the denominator was "
                          "zero, never 100",
    "pct_covered_source_is_upper_bound":
        "1 when the replaced-ingredient count behind the denominator is a "
        "floor, so the percentage is a ceiling",
    "oxygen": "curated regime: aerobic | anaerobic | facultative | null. null "
              "means unknown and is rendered as unknown, never as anaerobic",
    "defined": "true | false | null; null means no source asserted it",
}


# A rename is only honest if the consumer is told. This block ships in
# catalog.json, summary.json and data/index.json so a script reading the old key
# finds out what happened instead of finding the key missing.
FIELD_RENAMES = [
    {
        "old": "pct_covered_observed",
        "new": "pct_sourced_components_with_bigg_id",
        "changed": "2026-09-06",
        "why": ("The old name read as coverage of the medium, but its denominator "
                "is the components the record already carries rather than the "
                "ingredients the source listed, so it is a near-constant "
                "(measured below). It answers one question only: of the "
                "components the source states, the share that reached a BiGG id "
                "rather than a non-BiGG fallback or nothing. The coverage "
                "question is answered by pct_covered_source."),
        # filled by build_payload from the corpus, so the claim that the field was
        # near-constant carries its own denominator rather than an adjective
        "measured": None,
    },
]


#: Payload keys that record the BUILD rather than the DATA.
BUILD_STAMP_FIELDS = ("built_utc", "git_head")


def _payload_view(obj: dict) -> str:
    """The file's content with the build stamp removed, canonically serialised."""
    return json.dumps({k: v for k, v in obj.items() if k not in BUILD_STAMP_FIELDS},
                      separators=(",", ":"), ensure_ascii=False)


def write_payload_file(path: str, obj: dict) -> tuple[str, bool]:
    """Write one payload file, leaving it untouched when only the stamp would move.

    `make derived` stamped a fresh built_utc and git_head into all six data/web
    files on every run, so the six files always differed from the ones committed,
    and two things followed that nobody wanted:

      * `make preflight` could never pass. It runs `derived` and then
        `manifest-check --check-tree`, which hashes each artifact and compares it
        with the COMMITTED blob — the check that exists because CI once would have
        committed a manifest describing a payload it had not committed. With a
        wall-clock stamp inside the hashed bytes, that comparison was guaranteed to
        fail from a clean tree: `git diff --numstat` showed exactly one line changed
        per file and the content byte-identical otherwise. A gate that is red no
        matter what the repository does teaches people to skip it.
      * the CI job's "derived artifacts unchanged — nothing to commit" branch was
        dead code. Every trigger committed and pushed ~5 MiB of data/web for a
        timestamp, forever, to a repository whose pack is already 1.3 GiB.

    The fix is at the generator, and it is not to hash less: it is to stop claiming
    a build happened when nothing was built. The stamp now dates the build that last
    CHANGED the payload. If the data is identical, the previous stamp is kept and
    the file is not rewritten — not even its mtime — so `make derived` is idempotent
    and a git diff on data/web means the data moved.

    Returns (the bytes now in the file, whether it was rewritten).
    """
    blob = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    old_raw = None
    if os.path.exists(path):
        with open(path, "rb") as fh:
            old_raw = fh.read()
        try:
            old = json.loads(old_raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            old = None
        if isinstance(old, dict) and _payload_view(old) == _payload_view(obj):
            kept = dict(obj)
            for f in BUILD_STAMP_FIELDS:
                if f in old:
                    kept[f] = old[f]
            blob = json.dumps(kept, separators=(",", ":"), ensure_ascii=False)
            if blob.encode("utf-8") == old_raw:
                return blob, False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(blob)
    return blob, True


def git_head(repo: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


class _Enc:
    """Dictionary encoder for a low-cardinality column. None stays None."""

    def __init__(self):
        self.tables: dict[str, dict] = {}

    def __call__(self, field: str, value):
        if value is None:
            return None
        table = self.tables.setdefault(field, {})
        if value not in table:
            table[value] = len(table)
        return table[value]

    def dump(self) -> dict:
        return {k: list(v) for k, v in self.tables.items()}


def _evidence_counts(rec: dict) -> list[int]:
    """Per-record component counts in the six evidence classes.

    Reads `tier_counts` where the chemistry stage wrote it, and otherwise counts
    the components directly. An unknown tier is a hard error rather than a
    silent drop into the calmest bucket: an unrecognised evidence value must be
    loud, which is the MEDIA-WEB-01 lesson about the bare `else` branch.
    """
    per = {c: 0 for c in CLASS_ORDER}
    counts = rec.get("tier_counts")
    if not counts:
        counts = {}
        for comp in rec["components"]:
            tier = comp.get("evidence_tier")
            counts[tier] = counts.get(tier, 0) + 1
    for tier, n in counts.items():
        cls = TIER_TO_CLASS.get(tier)
        if cls is None:
            raise ValueError(
                "record %s carries evidence_tier %r, which no evidence class in "
                "tools/web_payload.py claims. Add it to EVIDENCE_CLASSES with a "
                "definition, or the browser would render it in whichever chip "
                "happened to be last." % (rec["id"], tier))
        per[cls] += n
    return [per[c] for c in CLASS_ORDER]


def _modifier_rows(rec: dict) -> list[dict]:
    out = []
    for m in rec.get("modifiers") or []:
        out.append({
            "kind": m.get("kind"),
            "agent": m.get("agent"),
            "amount": m.get("amount"),
            "unit": m.get("unit"),
            "polarity": m.get("polarity"),
            "reflected_in_composition": m.get("reflected_in_composition"),
        })
    return out


def build_payload(media_dir: str, out_dir: str, repo: str = REPO,
                  quarantine: str | None = None) -> dict:
    """Read the corpus, write data/web/*.json, return a machine-readable report."""
    files = sorted(glob.glob(os.path.join(media_dir, "*.json")))
    # Cross-references live once in data/refs.json (stage 60), keyed off
    # components[].xref_id. refs.component_xref() also handles a corpus that has
    # not been through that stage and still carries them inline, so this builder
    # works on either shape.
    try:
        refs = R.load_refs(repo)
    except FileNotFoundError:
        refs = {"xrefs": {}, "notes": {}}
    if not files:
        raise SystemExit(
            "FATAL: no media under %s. The browser payload is never legitimately "
            "empty; writing one would replace a 13,515-record library with a "
            "confident zero." % media_dir)

    enc = _Enc()
    rows: list[list] = []
    postings: dict[str, list[int]] = {}
    compound_meta: dict[str, dict] = {}
    families: dict[str, dict] = {}
    # aggregates, every one with an explicit denominator written beside it
    agg = {k: {} for k in ("by_category", "by_source_db", "by_license",
                           "by_verification_status", "by_oxygen",
                           "by_commercial_use_ok", "by_food_group",
                           "by_collection")}
    class_totals = {c: 0 for c in CLASS_ORDER}
    totals = {"n_components": 0, "n_sourced": 0, "n_derived": 0,
              "n_uncovered": 0, "n_with_concentration_mM": 0,
              "n_with_source_amount": 0}
    # Where every component's exchange id actually landed. Counted from the
    # components themselves, not from the record's declared counters, and then
    # asserted against them: the site's opening sentence used to be "every one
    # mapped to a BiGG exchange", which was true of 664,000 of 665,582.
    exch = {"n_bigg_exchange": 0, "n_nonbigg_fallback": 0, "n_no_exchange": 0}
    # Components actually iterated. The exchange and cross-reference accountings are
    # asserted against THIS, not against the records' declared n_components: they
    # count what they walked, and a declared counter that disagrees is a separate
    # defect with its own check.
    n_components_seen = 0
    # How near-constant the renamed field actually is, measured here rather than
    # asserted in prose (blocker g: the old name read as coverage).
    n_bigg_id_pct_is_100 = 0
    n_bigg_id_pct_null = 0
    # README claimed every component "carries cross-references". Measured here.
    xrefs = {"n_components_with_a_cross_reference": 0,
             "n_components_with_none": 0}
    # Where the quantitative content comes from and under whose terms. The licence
    # documents and the methods page state this in prose; the numbers are measured
    # here so the page can bind them instead of carrying a typed 14,341 that four
    # corrections outlived.
    conc_by_license: dict[str, int] = {}
    conc_by_source_db: dict[str, int] = {}
    conc_by_commercial_use_ok: dict[str, int] = {}
    degeneracy = Degeneracy()
    row_of_id: dict[str, int] = {}
    bands_source = {"high_ge_90": 0, "mid_60_90": 0, "review_lt_60": 0,
                    "not_computed": 0}
    n_upper_bound = 0
    n_any_derived = 0
    n_all_derived = 0
    licence_terms: dict[str, dict] = {}

    def bump(key, value):
        table = agg[key]
        table[str(value)] = table.get(str(value), 0) + 1

    for i, path in enumerate(files):
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        prov = rec.get("provenance") or {}
        cov = rec.get("coverage") or {}
        covs = rec.get("coverage_source") or {}
        quant = rec.get("quantitation") or {}
        fam = rec.get("family") or {}
        ev = _evidence_counts(rec)
        for cls, n in zip(CLASS_ORDER, ev):
            class_totals[cls] += n

        rec_bigg = rec_fallback = rec_none = 0
        n_components_seen += len(rec["components"])
        for comp in rec["components"]:
            # `xref_id` is the reference-table form of the same fact: stage 60
            # moves repeated cross-reference blocks into data/refs.json and leaves
            # an id behind, and an ABSENT id means no cross-references at all. Both
            # shapes are counted so this number survives that migration.
            if (comp.get("xref") or comp.get("target_xref")
                    or comp.get("source_xref") or comp.get("xref_id")):
                xrefs["n_components_with_a_cross_reference"] += 1
            else:
                xrefs["n_components_with_none"] += 1
            if not comp.get("exchange"):
                rec_none += 1
            elif comp.get("evidence_tier") == "non_bigg_fallback":
                rec_fallback += 1
            else:
                rec_bigg += 1
        exch["n_bigg_exchange"] += rec_bigg
        exch["n_nonbigg_fallback"] += rec_fallback
        exch["n_no_exchange"] += rec_none
        row_of_id[rec["id"]] = i
        degeneracy.add(rec)
        pct_bigg = rec.get("pct_sourced_components_with_bigg_id",
                           rec.get("pct_covered_observed"))
        if pct_bigg is None:
            n_bigg_id_pct_null += 1
        elif pct_bigg == 100.0:
            n_bigg_id_pct_is_100 += 1

        n_components = rec.get("n_components")
        n_sourced = covs.get("n_sourced")
        n_derived = rec.get("n_derived")
        n_uncovered = cov.get("n_uncovered")
        pcs = covs.get("pct_covered_source")
        upper = bool(covs.get("pct_covered_source_is_upper_bound"))
        n_upper_bound += 1 if upper else 0
        if n_derived:
            n_any_derived += 1
            if n_components and n_derived == n_components:
                n_all_derived += 1

        totals["n_components"] += n_components or 0
        totals["n_sourced"] += n_sourced or 0
        totals["n_derived"] += n_derived or 0
        totals["n_uncovered"] += n_uncovered or 0
        totals["n_with_concentration_mM"] += quant.get("n_with_concentration_mM") or 0
        totals["n_with_source_amount"] += quant.get("n_with_source_amount") or 0

        n_conc = quant.get("n_with_concentration_mM") or 0
        if n_conc:
            for table, key in ((conc_by_license, str(prov.get("license"))),
                               (conc_by_source_db, prov.get("source_name")),
                               (conc_by_commercial_use_ok,
                                str(prov.get("commercial_use_ok")))):
                table[key] = table.get(key, 0) + n_conc

        if pcs is None:
            bands_source["not_computed"] += 1
        elif pcs >= 90:
            bands_source["high_ge_90"] += 1
        elif pcs >= 60:
            bands_source["mid_60_90"] += 1
        else:
            bands_source["review_lt_60"] += 1

        bump("by_category", rec.get("category"))
        bump("by_source_db", prov.get("source_name"))
        bump("by_license", prov.get("license"))
        bump("by_verification_status", prov.get("verification_status"))
        bump("by_oxygen", rec.get("oxygen"))
        bump("by_commercial_use_ok", prov.get("commercial_use_ok"))
        if rec.get("food_group"):
            bump("by_food_group", rec.get("food_group"))
        if prov.get("collection"):
            bump("by_collection", prov.get("collection"))

        lic = prov.get("license")
        if lic and lic not in licence_terms:
            licence_terms[lic] = {
                "license": lic,
                "license_url": prov.get("license_url"),
                "commercial_use": prov.get("commercial_use"),
                "commercial_use_ok": prov.get("commercial_use_ok"),
                "attribution_required": prov.get("attribution_required"),
                "n_media": 0,
                "sources": [],
            }
        if lic:
            licence_terms[lic]["n_media"] += 1
            src = prov.get("source_name")
            if src and src not in licence_terms[lic]["sources"]:
                licence_terms[lic]["sources"].append(src)

        rows.append([
            rec["id"],
            rec.get("name_display") or rec.get("name"),
            enc("category", rec.get("category")),
            enc("source_db", prov.get("source_name")),
            enc("license", lic),
            prov.get("commercial_use_ok"),
            enc("verification_status", prov.get("verification_status")),
            enc("oxygen", rec.get("oxygen")),
            enc("organism_scope", rec.get("organism_scope")),
            n_components, n_sourced, n_derived, n_uncovered,
            pcs, 1 if upper else 0,
            enc("family", fam.get("id")),
            quant.get("n_with_concentration_mM"),
            enc("food_group", rec.get("food_group")),
            rec.get("defined"),
            rec_fallback, rec_none,
            None,   # model_input_twins: patched below, once the whole corpus is read
        ] + ev)

        seen = set()
        for comp in rec["components"]:
            ex = comp.get("exchange")
            if not ex or ex in seen:
                continue
            seen.add(ex)
            postings.setdefault(ex, []).append(i)
            if ex not in compound_meta:
                xr = R.component_xref(comp, refs)
                compound_meta[ex] = {
                    "bigg": comp.get("bigg_metabolite"),
                    "name": comp.get("target_name") or comp.get("name"),
                    "formula": xr.get("formula"),
                    "inchikey": xr.get("inchikey"),
                    "kegg": xr.get("kegg"),
                    "chebi": xr.get("chebi"),
                    "hmdb": xr.get("hmdb"),
                    "seed": xr.get("seed"),
                }

        fid = fam.get("id")
        if fid:
            entry = families.setdefault(fid, {
                "id": fid,
                "label": fam.get("label"),
                "method": fam.get("method"),
                "members": [],
            })
            entry["members"].append({
                "id": rec["id"],
                "name": rec.get("name_display") or rec.get("name"),
                "evidence": fam.get("evidence"),
                "composition_corroborated": fam.get("composition_corroborated"),
                "corroboration_blocked_reason": fam.get("corroboration_blocked_reason"),
                "modifiers": _modifier_rows(rec),
                "modifiers_unparsed": rec.get("modifiers_unparsed"),
                "strength": rec.get("strength"),
                "preparation": rec.get("preparation"),
                "ph_declared": rec.get("ph_declared"),
                "oxygen": rec.get("oxygen"),
                "n_components": n_components,
                "n_sourced": n_sourced,
                "n_derived": n_derived,
                "pct_covered_source": pcs,
                "pct_covered_source_is_upper_bound": upper,
                "composition_signature": rec.get("composition_signature"),
                "composition_identical_to": rec.get("composition_identical_to") or [],
                "source_db": prov.get("source_name"),
                "license": lic,
                "commercial_use_ok": prov.get("commercial_use_ok"),
                "citation": prov.get("citation"),
            })

    n = len(rows)

    # --- the model-input twins, now that the whole corpus has been read -------
    # A per-record answer to "is anything else identical to this?" cannot be given
    # in one pass, so the column is filled here rather than guessed above.
    twin_col = COLUMNS.index("model_input_twins")
    for mid, ri in row_of_id.items():
        rows[ri][twin_col] = degeneracy.n_twins(mid)
    degen = degeneracy.report()
    twin_groups = degeneracy.groups()
    field_renames = [
        dict(FIELD_RENAMES[0], measured={
            "n_records_where_the_value_is_100.0": n_bigg_id_pct_is_100,
            "n_records_where_it_is_null": n_bigg_id_pct_null,
            "of": n,
        })
    ]

    n_conc_total = totals["n_with_concentration_mM"]
    n_conc_restricted = conc_by_commercial_use_ok.get("False", 0)
    _top = max(conc_by_source_db.items(), key=lambda kv: kv[1]) \
        if conc_by_source_db else None
    concentration_provenance = {
        "n_with_concentration_mM": n_conc_total,
        "of": n_components_seen,
        "by_source_db": dict(sorted(conc_by_source_db.items(),
                                    key=lambda kv: -kv[1])),
        "by_license": dict(sorted(conc_by_license.items(), key=lambda kv: -kv[1])),
        "by_commercial_use_ok": conc_by_commercial_use_ok,
        "n_from_media_that_may_not_be_used_commercially": n_conc_restricted,
        "n_from_media_that_may": n_conc_total - n_conc_restricted,
        "largest_contributor": None if _top is None else {
            "source_db": _top[0], "n": _top[1], "of": n_conc_total},
        "definition": (
            "Where the resource's quantitative content comes from, and under whose "
            "terms. A component counts when its concentration_mM is not null. The "
            "methods page binds these numbers rather than stating them, because the "
            "denominator was corrected from 14,341 and a typed copy survived the "
            "correction on the shipped page."),
    }

    # --- consistency: the payload's totals must be the corpus's totals --------
    if sum(conc_by_license.values()) != n_conc_total:
        raise ValueError(
            "the licence tally covers %d of the %d components carrying a "
            "concentration. A concentration with no licence beside it is how the "
            "site stated a redistribution exposure nobody had measured."
            % (sum(conc_by_license.values()), n_conc_total))
    if sum(xrefs.values()) != n_components_seen:
        raise ValueError(
            "cross-reference accounting covers %d of the %d components walked"
            % (sum(xrefs.values()), n_components_seen))
    if sum(exch.values()) != n_components_seen:
        raise ValueError(
            "exchange resolution accounts for %d of the %d components walked. "
            "Every component is BiGG-mapped, carries a non-BiGG fallback, or has "
            "no exchange; a fourth state would let the site state a mapping claim "
            "it cannot support." % (sum(exch.values()), n_components_seen))
    if sum(len(g) for g in twin_groups) != degen["n_media_sharing_a_model_input"]:
        raise ValueError("model-input groups and the degeneracy total disagree")
    if sum(class_totals.values()) != totals["n_components"]:
        raise ValueError(
            "evidence classes cover %d components but the records declare %d. "
            "A component that falls outside the six classes would be invisible "
            "in the browser's evidence bar while still being counted in the "
            "component total."
            % (sum(class_totals.values()), totals["n_components"]))
    if sum(bands_source.values()) != n:
        raise ValueError("source-coverage bands sum to %d of %d media"
                         % (sum(bands_source.values()), n))

    for entry in families.values():
        sigs = {m["composition_signature"] for m in entry["members"]
                if m["composition_signature"]}
        entry["n_members"] = len(entry["members"])
        entry["n_distinct_compositions"] = len(sigs) or None
        entry["n_members_of"] = n
        axes: dict[str, list] = {}
        for m in entry["members"]:
            for mod in m["modifiers"]:
                kind = mod.get("kind") or "other"
                agent = mod.get("agent")
                if agent and agent not in axes.setdefault(kind, []):
                    axes[kind].append(agent)
        entry["modifier_axes"] = {k: sorted(v) for k, v in sorted(axes.items())}
        entry["members"].sort(key=lambda m: (m["name"] or "").lower())

    fam_list = sorted(families.values(),
                      key=lambda f: (-f["n_members"], f["id"]))
    n_in_family = sum(f["n_members"] for f in fam_list)

    built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    head = git_head(repo)
    stamp = {
        "schema": SCHEMA,
        "built_utc": built,
        "git_head": head,
        "stamp_policy": ("built_utc and git_head date the build that last CHANGED "
                         "this payload, not the last time the builder ran: a "
                         "rebuild that reproduces these bytes leaves the file, and "
                         "this stamp, alone. So a diff on this file means its data "
                         "changed."),
        "corpus": os.path.relpath(media_dir, repo),
        "count": n,
        "count_authority": ("data/media/*.json on disk, counted by "
                            "tools/web_payload.py in the same pass that wrote "
                            "every number below"),
    }

    catalog = dict(stamp)
    catalog.update({
        "doc": ("Browser payload. Rows are arrays; zip them against `columns`. "
                "The enum columns listed in `enum_columns` are dictionary-"
                "encoded against `dicts`. The readable, documented catalog is "
                "data/index.json; this file exists so the landing page does not "
                "have to transfer 16.7 MB to draw a table."),
        "columns": COLUMNS,
        "enum_columns": list(ENUM_COLUMNS),
        "column_notes": COLUMN_NOTES,
        "evidence_classes": [
            {"id": c["id"], "label": c["label"], "definition": c["definition"],
             "tiers": c["tiers"], "n": class_totals[c["id"]],
             "of": totals["n_components"]}
            for c in EVIDENCE_CLASSES],
        "component_totals": dict(totals, of=totals["n_components"]),
        "exchange_resolution": dict(
            exch, of=n_components_seen,
            definition=(
                "Where each component's exchange id landed. n_bigg_exchange is a "
                "real BiGG EX_<met>_e reaction. n_nonbigg_fallback is a "
                "ModelSEED/MetaNetX/KEGG id in exchange position: the component's "
                "own mapping_note says no BiGG model will accept it. "
                "n_no_exchange has none at all. The three partition "
                "n_components, and the site states all three rather than "
                "claiming every component is BiGG-mapped.")),
        "cross_references": dict(
            xrefs, of=n_components_seen,
            definition=(
                "A component counts as carrying a cross-reference when it has any "
                "of xref, target_xref or source_xref. Those describe the BiGG "
                "metabolite that was chosen and, for source_xref, the identifier "
                "the source supplied; only source_xref is independent evidence.")),
        "concentration_provenance": concentration_provenance,
        "model_input_degeneracy": degen,
        "field_renames": field_renames,
        "media_totals": {
            "n_media": n,
            "n_media_with_any_derived_component": n_any_derived,
            "n_media_entirely_derived": n_all_derived,
            "n_media_source_coverage_is_upper_bound": n_upper_bound,
            "n_media_in_a_family": n_in_family,
            "n_media_without_a_family": n - n_in_family,
            "of": n,
        },
        "coverage_bands_source": dict(bands_source, of=n),
        "n_exchanges": len(postings),
        "n_uncovered_ingredients": totals["n_uncovered"],
        "licences": sorted(licence_terms.values(),
                           key=lambda x: -x["n_media"]),
        "dicts": enc.dump(),
        "rows": rows,
    })
    for key, table in agg.items():
        catalog[key] = dict(table, _of=n)

    compounds = dict(stamp)
    compounds.update({
        "doc": ("Complete exchange -> media inverted index over all %d media. "
                "`postings` values are delta-encoded row indices into "
                "catalog.json `rows`; `meta` carries the cross-references so a "
                "compound can be resolved by structure (InChIKey, formula) and "
                "not only by name." % n),
        "n_exchanges": len(postings),
        "n_media": n,
        "meta": compound_meta,
        "postings": {ex: _delta(sorted(v)) for ex, v in postings.items()},
    })

    fam_payload = dict(stamp)
    fam_payload.update({
        "doc": ("Base-medium families. `method` records how the family was "
                "decided; `composition_corroborated` is the share of the "
                "family's canonical composition the record actually contains, "
                "and null where corroboration was blocked (the reason is "
                "given). A family is a naming grouping, never a claim that the "
                "variants are interchangeable."),
        "n_families": len(fam_list),
        "n_media_in_a_family": n_in_family,
        "n_media_without_a_family": n - n_in_family,
        "n_media": n,
        "families": fam_list,
    })

    tomb = dict(stamp)
    tomb.update(_tombstones(quarantine or os.path.join(repo, "data",
                                                       "_quarantine.json")))

    # The twin groups, named. The catalog column says HOW MANY other records share
    # a record's model input; this file says WHICH, so the record sheet can list
    # them instead of leaving the reader to guess. Ids appear once: the reverse
    # map is built by the client on load rather than shipped twice.
    twins = dict(stamp)
    twins.update({
        "doc": ("Groups of media that hand a genome-scale model the identical "
                "constraint set. Membership is transitive and complete: every id "
                "in a group produces the same model input as every other id in "
                "it. A medium absent from every group has a model input unique "
                "in this library."),
        "groups": twin_groups,
        **degen,
    })

    # summary.json is catalog.json without the 13,515 rows: the pages that need only
    # the library-wide numbers (methods, patterns) transfer 100 KB instead of 2 MB.
    summary = {k: v for k, v in catalog.items()
               if k not in ("rows", "dicts", "columns", "enum_columns")}
    summary["doc"] = ("Library-wide aggregates only, for pages that render no per-medium "
                      "rows. Identical values to catalog.json, same build.")

    os.makedirs(out_dir, exist_ok=True)
    written = {}
    for name, obj in (("catalog.json", catalog), ("summary.json", summary),
                      ("compounds.json", compounds),
                      ("families.json", fam_payload),
                      ("tombstones.json", tomb),
                      ("twins.json", twins)):
        path = os.path.join(out_dir, name)
        blob, rewritten = write_payload_file(path, obj)
        raw = len(blob.encode("utf-8"))
        written[name] = {"bytes": raw, "rewritten": rewritten,
                         "bytes_gzip": len(gzip.compress(blob.encode("utf-8"), 6))}

    return {
        "out_dir": os.path.relpath(out_dir, repo),
        "media_read": n,
        "written": written,
        "component_totals": totals,
        "evidence_class_totals": class_totals,
        "exchange_resolution": exch,
        "cross_references": xrefs,
        "concentration_provenance": concentration_provenance,
        "model_input_degeneracy": degen,
        "field_renames": field_renames,
        "coverage_bands_source": bands_source,
        "n_families": len(fam_list),
        "n_media_in_a_family": n_in_family,
        "n_exchanges": len(postings),
        "n_tombstones": tomb["n_withdrawn"],
        "built_utc": built,
        "git_head": head,
    }


def _delta(values: list[int]) -> list[int]:
    out, prev = [], 0
    for v in values:
        out.append(v - prev)
        prev = v
    return out


def _tombstones(path: str) -> dict:
    """The withdrawn records, with the prose reason rather than the machine code.

    COV-05: 74 of the 77 rows carry `reason` = "workflow:rejected" or
    "workflow:not_found", which are workflow codes, not curation reasoning.
    The reasoning is in `note`. Publishing the code under a heading that
    promises a reason would be a confident surface built on a machine string,
    so the payload states which of the two it has for each record and counts
    the rows for which no prose exists.
    """
    if not os.path.isfile(path):
        return {"n_withdrawn": 0, "records": {}, "reasons": {},
                "n_with_prose": 0,
                "assessed_denominator": None,
                "why_no_denominator": (
                    "no quarantine ledger is present in this corpus")}
    with open(path, encoding="utf-8") as fh:
        entries = json.load(fh)
    records, reasons, with_prose = {}, {}, 0
    for e in entries:
        code = e.get("reason")
        reasons[code] = reasons.get(code, 0) + 1
        note = e.get("note")
        if note:
            with_prose += 1
        records[e["id"]] = {
            "name": e.get("name"),
            "code": code,
            "note": note,
            "evidence": e.get("evidence"),
        }
    return {
        "n_withdrawn": len(entries),
        "n_with_prose": with_prose,
        "n_without_prose": len(entries) - with_prose,
        "reasons": reasons,
        "assessed_denominator": None,
        "why_no_denominator": (
            "The verification pass recorded what it rejected but not how many "
            "records it assessed, so 77 has no denominator to divide by. It is "
            "reported as a count, never as a rate."),
        "records": records,
    }
