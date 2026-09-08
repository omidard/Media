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
  tombstones.json  the 77 withdrawn identifiers, each resolving to its name and
                   to one class-level reason code, so a rotted `?medium=`
                   permalink states the identifier's state instead of rendering
                   an ordinary landing page. The per-record review prose lives
                   in tools/curation/tombstone_reason_codes.tsv and ships
                   nowhere.
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
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataset_license import DATASET_LICENSE   # noqa: E402
from model_input import Degeneracy           # noqa: E402
import build_bigg_exchange_ids               # noqa: E402
import refs as R                             # noqa: E402

SCHEMA = "mediadb-web-payload/1"

# Where an exchange id actually lands, in four states rather than three. The
# partition used to be decided by the STRING SHAPE of the id, so 11,380 components
# naming a reaction BiGG does not have were counted as reaching one and the page
# warned about 1,364 unusable ids when the figure was 12,744. One definition,
# shared with build_index.py and build_coverage_index.py, so the three cannot drift.
exchange_state = build_bigg_exchange_ids.exchange_state

# --------------------------------------------------------------------------
# An oxygen regime nobody stated is not a regime.
#
# tools/curate_oxygen.py ends in two catch-all branches that return
# "facultative" when the source says nothing at all about oxygen, and records
# WHY in oxygen_note. 11,926 of the 12,136 facultative records carry one of these
# two notes: 88% of the library was handed a curated-looking regime that no
# source asserted, in the field the site itself calls the single most
# consequential bound in an FBA medium.
#
# It was invisible, and worse than invisible. index.html offers "Facultative" and
# "Unknown (not recorded)" as separate filter states and gates the second on
# `oxygen !== null`, so a modeller filtering for the records where they must
# decide EX_o2_e themselves got 439 and silently missed 11,926 that need the same
# decision. methods.html rendered "The oxygen regime is not recorded for 439 of
# 13,515 media", understating the unknown set by a factor of 28.
#
# The regime published here is now the RECORDED one: null where nothing was
# recorded, which is exactly what this payload's own column note has always
# claimed it means. What the exported medium does with EX_o2_e is a separate
# fact and is published separately, so the curated regime and the simulation
# convention can never again be the same number.
#
# NOT applied to the 71 records whose regime is `aerobic` while carrying one of
# these notes: those were set by a curator and kept a note from a run that
# predates the verification guard. The stale note is a separate defect and is in
# the ledger; treating them here would erase a real curation.
OXYGEN_NOT_STATED_NOTES = (
    "food substrate; O2 availability is a simulation condition, not a property "
    "of the food",
    "no oxygen requirement specified; O2 available but not asserted",
)


def oxygen_recorded(rec):
    """(regime actually recorded, regime the exported medium assumes).

    The first is null when no source or curator stated one. The second is what
    EX_o2_e was written from, which is a convention of the build and is labelled
    as one on every component that carries it.

    A record that already carries `oxygen_default_for_simulation` has been through
    43_oxygen_regime_absent_when_unstated and separates the two facts itself, so
    it is read rather than re-derived: re-applying the note rule to a corrected
    record would find `oxygen` null instead of "facultative", return (None, None),
    and silently drop n_no_source_statement from 11,926 to 0. The two branches
    agree on every record either way, which is what lets the correction land in
    the corpus without moving a published number.
    """
    if "oxygen_default_for_simulation" in rec:
        return rec.get("oxygen"), rec.get("oxygen_default_for_simulation")
    regime = rec.get("oxygen")
    note = (rec.get("oxygen_note") or "").strip()
    if regime == "facultative" and note in OXYGEN_NOT_STATED_NOTES:
        return None, regime
    return regime, regime

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
        "label": "Derived",
        "tiers": ["derived_component"],
        "definition": (
            "The cited source never states this component. It comes from "
            "decomposing a complex ingredient, approximating a hydrolysate, or "
            "a standard mineral or oxygen base added by convention. It is an "
            "in-silico addition, marked on every record that carries it and "
            "excluded from every source-coverage figure."),
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
    "id", "name", "category", "source_db",
    "verification_status", "oxygen", "oxygen_default_for_simulation",
    "organism_scope",
    "n_components", "n_sourced", "n_derived", "n_uncovered",
    "pct_covered_source", "pct_covered_source_is_upper_bound", "family",
    "n_with_concentration_mM", "food_group", "defined",
    # The three ways a component can fail to reach a usable BiGG exchange, per
    # record. Two of them were published; the third was counted as a success, so
    # 5,719 records reported zero unusable components while carrying one.
    "n_nonbigg_fallback", "n_no_exchange", "n_bigg_shaped_no_such_exchange",
    # How many OTHER records hand a model the identical constraint set (0 = unique).
    "model_input_twins",
] + ["ev_" + c for c in CLASS_ORDER]

ENUM_COLUMNS = ("category", "source_db", "verification_status",
                "oxygen", "oxygen_default_for_simulation", "organism_scope",
                "family", "food_group")

COLUMN_NOTES = {
    "n_components": "components in the record. Most carry a usable BiGG exchange; "
                    "n_nonbigg_fallback, n_no_exchange and "
                    "n_bigg_shaped_no_such_exchange say how many do not",
    "n_nonbigg_fallback": "of n_components, the number whose exchange id is a "
                           "ModelSEED/MetaNetX/KEGG fallback, not a BiGG id. No "
                           "BiGG model will accept it. 1,364 of 665,582 "
                           "components library-wide",
    "n_no_exchange": "of n_components, the number with no exchange reaction at "
                     "all: identity was never established, or the ingredient is "
                     "an undefined mixture. 218 of 665,582 library-wide",
    "n_bigg_shaped_no_such_exchange":
        "of n_components, the number whose exchange id has the EX_<met>_e shape "
        "but is not in BiGG's exchange-reaction list, so no model has it and the "
        "documented adoption path drops it silently. 12,228 of 665,582 components "
        "library-wide; the largest is EX_choles_e (4,438), where "
        "BiGG carries choles_c only and cholesterol's exchange is EX_chsterol_e",
    "model_input_twins": "how many OTHER records hand a model the identical set "
                         "of (exchange, lower bound, upper bound) triples. 0 "
                         "means this record's model input is unique in the "
                         "library; see model_input_degeneracy",
    "n_sourced": "of those, the number the cited source actually states",
    "n_derived": "of those, the number the cited source does not state (the "
                 "derived evidence class)",
    "n_uncovered": "ingredients the source states that got no exchange at all; "
                   "they are NOT in n_components",
    "pct_covered_source": "share of the source's own ingredient list that "
                          "reached an exchange. null means the denominator was "
                          "zero, never 100",
    "pct_covered_source_is_upper_bound":
        "1 when the replaced-ingredient count behind the denominator is a "
        "floor, so the percentage is a ceiling",
    "oxygen_default_for_simulation":
        "what EX_o2_e in the exported medium was written from. A convention, not "
        "a finding: it is present even where oxygen is null, and the O2 component "
        "itself is marked derived on every record that carries it",
    "oxygen": "RECORDED regime: aerobic | anaerobic | facultative | null. null "
              "means no source or curator stated one, is rendered as unknown, and "
              "is never anaerobic. It is null on the 11,926 records whose "
              "oxygen_note says the source stated nothing; the per-record file "
              "still carries the pipeline's facultative default there, and "
              "oxygen_default_for_simulation carries it here",
    "defined": "true | false | null; null means no source asserted it",
}


# The rename map a client holding the old key resolves against. It ships in
# catalog.json, summary.json and data/index.json. It carries the two names and
# what the field measures; the reasoning behind the rename is not documentation
# a consumer of the field can act on, so it is not published.
FIELD_RENAMES = [
    {
        "old": "pct_covered_observed",
        "new": "pct_sourced_components_with_bigg_id",
        "changed": "2026-09-06",
        "measures": ("of the components the cited source states, the share that "
                     "reached a BiGG metabolite id rather than a non-BiGG "
                     "fallback or nothing. Its denominator is components, not "
                     "the source's ingredient list, so it is not a coverage "
                     "measure; coverage is pct_covered_source."),
        # filled by build_payload from the corpus, so the field's near-constant
        # distribution is a measurement with a denominator, not an adjective
        "measured": None,
    },
]


# ---------------------------------------------------------------------------
# Withdrawn identifiers.
#
# A withdrawn identifier resolves to its state and to ONE class-level reason
# code, the pattern UniProt uses for deleted accessions and the wwPDB for
# obsolete entries. The reviewer's per-record prose and the source excerpt it
# was read from stay in tools/curation/tombstone_reason_codes.tsv, which is a
# curation table and is not projected into any payload or page.
# ---------------------------------------------------------------------------
TOMBSTONE_REASON_CODES = [
    {
        "code": "composition_not_stated",
        "label": "Composition not stated by the source",
        "definition": ("The cited source names the medium and does not state its "
                       "composition; the formulation sits in another work, in "
                       "material outside the article, or in a commercial product."),
    },
    {
        "code": "not_a_defined_medium",
        "label": "Not a defined growth medium",
        "definition": ("The entry is an environmental sample, an undefined complex "
                       "substrate, a buffer or an in-vivo condition, so it has no "
                       "formulation to state."),
    },
    {
        "code": "extraction_artifact",
        "label": "Extraction artifact",
        "definition": ("The composition on the record is not the one the cited "
                       "source states: it merges distinct media or mutually "
                       "exclusive conditions, or carries components the source "
                       "does not give."),
    },
    {
        "code": "no_composition_recorded",
        "label": "No composition recorded",
        "definition": "The record carries no components to serve.",
    },
]
TOMBSTONE_CODES = {c["code"] for c in TOMBSTONE_REASON_CODES}
REASON_CODE_TABLE = os.path.join(REPO, "tools", "curation",
                                 "tombstone_reason_codes.tsv")


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


def corpus_digest(media_dir: str) -> str:
    """sha256 over every record's bytes, in sorted id order. 12 hex published.

    THE STAMP USED TO NAME A COMMIT THAT COULD NOT CONTAIN THESE BYTES. It was
    `git rev-parse HEAD` read at build time, so it named the tree the builder was
    STANDING ON, and the payload it stamped could only be committed afterwards.
    That is structural, not a slip: checking out the stamped commit and rebuilding
    can never reproduce the stamped payload. Measured on the shipped release, the
    stamp named a commit five behind, whose own catalog.json publishes
    n_bigg_exchange 664,000 against the shipped 652,620 and does not even contain
    tools/build_bigg_exchange_ids.py, the module that computes the four-state
    partition. methods.html asks a scientist to cite the release stamp, so the one
    identifier the page tells you to quote did not resolve to these numbers.

    A digest of the corpus is recomputable from any checkout, by the reader, with
    no repository history at all, and it identifies the bytes rather than a tree
    that might contain them:

        find data/media -name '*.json' | sort | xargs cat | sha256sum
    """
    h = hashlib.sha256()
    for name in sorted(os.listdir(media_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(media_dir, name), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:12]


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
                  quarantine: str | None = None,
                  reason_codes: str | None = None) -> dict:
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
    agg = {k: {} for k in ("by_category", "by_source_db",
                           "by_verification_status", "by_oxygen",
                           "by_food_group", "by_collection")}
    class_totals = {c: 0 for c in CLASS_ORDER}
    totals = {"n_components": 0, "n_sourced": 0, "n_derived": 0,
              "n_uncovered": 0, "n_with_concentration_mM": 0,
              "n_with_source_amount": 0}
    # Where every component's exchange id actually landed. Counted from the
    # components themselves, not from the record's declared counters, and then
    # asserted against them: the site's opening sentence used to be "every one
    # mapped to a BiGG exchange", which was true of 664,000 of 665,582.
    exch = {"n_bigg_exchange": 0, "n_bigg_shaped_no_such_exchange": 0,
            "n_nonbigg_fallback": 0, "n_no_exchange": 0}
    # The distinct ids in the fourth state, so a record sheet can mark the rows a
    # model will silently drop. 294 strings, published in the payload the record
    # sheet already loads, rather than a second fetch of the 2,472-entry BiGG
    # vocabulary. Rebuilt with the corpus, so it cannot fall out of step with it.
    unusable_exchange_ids: dict[str, int] = {}
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
    # Which source each quantitative value comes from. The documents and the methods
    # page state this in prose; the numbers are measured here so the page binds them
    # instead of carrying a typed figure.
    conc_by_source_db: dict[str, int] = {}
    degeneracy = Degeneracy()
    row_of_id: dict[str, int] = {}
    bands_source = {"high_ge_90": 0, "mid_60_90": 0, "review_lt_60": 0,
                    "not_computed": 0}
    n_upper_bound = 0
    n_oxygen_defaulted = 0
    n_oxygen_null = 0
    n_any_derived = 0
    n_all_derived = 0

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

        rec_bigg = rec_fallback = rec_none = rec_noreaction = 0
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
            state = exchange_state(comp)
            if state == "n_no_exchange":
                rec_none += 1
            elif state == "n_nonbigg_fallback":
                rec_fallback += 1
            elif state == "n_bigg_shaped_no_such_exchange":
                rec_noreaction += 1
                ex_id = comp["exchange"]
                unusable_exchange_ids[ex_id] = unusable_exchange_ids.get(ex_id, 0) + 1
            else:
                rec_bigg += 1
        exch["n_bigg_exchange"] += rec_bigg
        exch["n_nonbigg_fallback"] += rec_fallback
        exch["n_bigg_shaped_no_such_exchange"] += rec_noreaction
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
            key = prov.get("source_name")
            conc_by_source_db[key] = conc_by_source_db.get(key, 0) + n_conc

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
        bump("by_verification_status", prov.get("verification_status"))
        oxygen, oxygen_default = oxygen_recorded(rec)
        bump("by_oxygen", oxygen)
        if oxygen is None:
            n_oxygen_null += 1
            if oxygen_default is not None:
                n_oxygen_defaulted += 1
        if rec.get("food_group"):
            bump("by_food_group", rec.get("food_group"))
        if prov.get("collection"):
            bump("by_collection", prov.get("collection"))

        rows.append([
            rec["id"],
            rec.get("name_display") or rec.get("name"),
            enc("category", rec.get("category")),
            enc("source_db", prov.get("source_name")),
            enc("verification_status", prov.get("verification_status")),
            enc("oxygen", oxygen),
            enc("oxygen_default_for_simulation", oxygen_default),
            enc("organism_scope", rec.get("organism_scope")),
            n_components, n_sourced, n_derived, n_uncovered,
            pcs, 1 if upper else 0,
            enc("family", fam.get("id")),
            quant.get("n_with_concentration_mM"),
            enc("food_group", rec.get("food_group")),
            rec.get("defined"),
            rec_fallback, rec_none, rec_noreaction,
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
                "oxygen": oxygen,
                "oxygen_default_for_simulation": oxygen_default,
                "n_components": n_components,
                "n_sourced": n_sourced,
                "n_derived": n_derived,
                "pct_covered_source": pcs,
                "pct_covered_source_is_upper_bound": upper,
                "composition_signature": rec.get("composition_signature"),
                "composition_identical_to": rec.get("composition_identical_to") or [],
                "source_db": prov.get("source_name"),
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
    _top = max(conc_by_source_db.items(), key=lambda kv: kv[1]) \
        if conc_by_source_db else None
    concentration_provenance = {
        "n_with_concentration_mM": n_conc_total,
        "of": n_components_seen,
        "by_source_db": dict(sorted(conc_by_source_db.items(),
                                    key=lambda kv: -kv[1])),
        "largest_contributor": None if _top is None else {
            "source_db": _top[0], "n": _top[1], "of": n_conc_total},
        "definition": (
            "Which source each quantitative value comes from. A component counts "
            "when its concentration_mM is not null."),
    }

    # --- consistency: the payload's totals must be the corpus's totals --------
    if sum(conc_by_source_db.values()) != n_conc_total:
        raise ValueError(
            "the source tally covers %d of the %d components carrying a "
            "concentration. A concentration with no source beside it is a number "
            "with no provenance."
            % (sum(conc_by_source_db.values()), n_conc_total))
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
    digest = corpus_digest(media_dir)
    # WHAT IDENTIFIES THIS RELEASE IS `corpus_sha256`, NOT `git_head`.
    #
    # git_head is read at build time, so it names the commit the builder was
    # standing on and the payload it stamps can only be committed afterwards: the
    # stamped commit can never contain the stamped bytes. On the shipped release
    # it named a commit five behind whose own catalog.json publishes a different
    # headline number and which does not contain the module that computes it. It
    # is kept, clearly labelled as the tree the build ran FROM, because it is
    # useful to whoever is debugging a build; it is no longer what the page tells
    # a reader to quote. corpus_sha256 identifies the bytes and any reader can
    # recompute it from a checkout with no history at all.
    #
    # The policy that keeps built_utc stable across a no-op rebuild is documented
    # at write_payload_file(), where it is enforced.
    stamp = {
        "schema": SCHEMA,
        "built_utc": built,
        "corpus_sha256": digest,
        "corpus_sha256_recompute":
            "find data/media -name '*.json' | sort | xargs cat | sha256sum",
        "git_head": head,
        "git_head_meaning":
            "the commit the BUILD RAN FROM, which cannot be the commit that "
            "contains this payload. Cite corpus_sha256 instead.",
        "corpus": os.path.relpath(media_dir, repo),
        "count": n,
        # One licence for the whole dataset. There is no per-record licence field
        # and no by-licence aggregate: the compilation is licensed at its most
        # restrictive input, so every record carries the same terms.
        "license": DATASET_LICENSE,
    }

    catalog = dict(stamp)
    catalog.update({
        "doc": ("Browser payload. Rows are arrays; zip them against `columns`. "
                "The enum columns listed in `enum_columns` are dictionary-"
                "encoded against `dicts`. The readable, documented catalog, one "
                "object per medium, is data/index.json."),
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
            bigg_shaped_no_such_exchange_ids=sorted(unusable_exchange_ids),
            definition=(
                "Where each component's exchange id landed, in four states. "
                "n_bigg_exchange is a reaction BiGG has: the id is in BiGG's own "
                "exchange-reaction list. That list is the test, not the "
                "metabolite's compartments: f_e exists in BiGG and EX_f_e does not. "
                "n_bigg_shaped_no_such_exchange is an id of that same shape that "
                "names no BiGG reaction, so no model has it and the documented "
                "adoption path drops it without a word (EX_choles_e is the "
                "largest: BiGG has choles_c only, and cholesterol's exchange is "
                "EX_chsterol_e). n_nonbigg_fallback is a ModelSEED/MetaNetX/KEGG "
                "id in exchange position: the component's own mapping_note says "
                "no BiGG model will accept it. n_no_exchange has none at all. The "
                "four partition n_components; the last three are all unusable to "
                "a model.")),
        "oxygen_basis": {
            "n_regime_recorded": n - n_oxygen_null,
            "n_no_source_statement": n_oxygen_defaulted,
            "n_absent_for_another_reason": n_oxygen_null - n_oxygen_defaulted,
            "of": n,
            "unstated_notes": list(OXYGEN_NOT_STATED_NOTES),
            "definition": (
                "How many records have an oxygen regime a source or a curator "
                "actually stated. n_no_source_statement counts the records whose "
                "own oxygen_note says nothing was stated: their regime is "
                "published here as null, and oxygen_default_for_simulation "
                "carries the facultative default the exported medium uses for "
                "EX_o2_e. unstated_notes is the vocabulary that decides it, so "
                "the browser applies the same rule to a per-record file as this "
                "payload applies to the catalogue."),
        },
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
    tomb.update(_tombstones(
        quarantine or os.path.join(repo, "data", "_quarantine.json"),
        reason_codes or REASON_CODE_TABLE))

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
                      "rows. The values are identical to catalog.json.")

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


def read_reason_code_table(path: str) -> dict[str, str]:
    """id -> reason code, from the curation table.

    The table also holds the reviewer's prose and the source excerpt behind each
    decision. Those two columns are read by nobody: they are the internal record,
    and this function returns only the code.
    """
    codes: dict[str, str] = {}
    if not os.path.isfile(path):
        return codes
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            cells = line.rstrip("\n").split("\t")
            if cells[0] == "id":
                continue
            if len(cells) < 2:
                raise ValueError("%s: row has no reason code: %r" % (path, line[:80]))
            mid, code = cells[0], cells[1]
            if code not in TOMBSTONE_CODES:
                raise ValueError(
                    "%s: %s carries reason code %r, which is not in the published "
                    "vocabulary %s. A code the payload cannot define would render "
                    "as a blank reason on the tombstone."
                    % (path, mid, code, sorted(TOMBSTONE_CODES)))
            codes[mid] = code
    return codes


def _tombstones(path: str, codes_path: str) -> dict:
    """The withdrawn identifiers: state, name, and one class-level reason code.

    COV-05: the ledger's own `reason` is a workflow string ("workflow:rejected",
    "workflow:not_found") on 74 of the 77 rows, and the review that produced it
    is per-record prose. Neither is documentation. The identifier resolves to a
    code from TOMBSTONE_REASON_CODES, each code carries its count and its
    denominator, and the prose stays in the curation table.
    """
    doc = ("Withdrawn identifiers. A withdrawn identifier names a medium that is "
           "not served by the browser or the API; it is not reassigned, and no "
           "other record is a substitute for it. `records` maps the identifier to "
           "its name and to one code in `reason_codes`.")
    if not os.path.isfile(path):
        return {"doc": doc, "n_withdrawn": 0, "records": {},
                "reason_codes": [dict(c, n=0, of=0)
                                 for c in TOMBSTONE_REASON_CODES]}
    with open(path, encoding="utf-8") as fh:
        entries = json.load(fh)
    codes = read_reason_code_table(codes_path)
    missing = sorted(e["id"] for e in entries if e["id"] not in codes)
    if missing:
        raise ValueError(
            "%d of %d withdrawn identifiers have no reason code in %s (%s%s). An "
            "identifier that resolves to no reason resolves to nothing."
            % (len(missing), len(entries), codes_path, ", ".join(missing[:3]),
               ", ..." if len(missing) > 3 else ""))
    records, counts = {}, {}
    for e in entries:
        code = codes[e["id"]]
        counts[code] = counts.get(code, 0) + 1
        records[e["id"]] = {"name": e.get("name"), "reason_code": code}
    return {
        "doc": doc,
        "n_withdrawn": len(entries),
        "reason_codes": [dict(c, n=counts.get(c["code"], 0), of=len(entries))
                         for c in TOMBSTONE_REASON_CODES],
        "records": records,
    }
