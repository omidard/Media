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
corpus into four small artifacts under `data/web/`, each of which carries the
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
] + ["ev_" + c for c in CLASS_ORDER]

ENUM_COLUMNS = ("category", "source_db", "license", "verification_status",
                "oxygen", "organism_scope", "family", "food_group")

COLUMN_NOTES = {
    "n_components": "components in the record; every one has a BiGG exchange",
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
        ] + ev)

        seen = set()
        for comp in rec["components"]:
            ex = comp.get("exchange")
            if not ex or ex in seen:
                continue
            seen.add(ex)
            postings.setdefault(ex, []).append(i)
            if ex not in compound_meta:
                xr = comp.get("xref") or {}
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

    # --- consistency: the payload's totals must be the corpus's totals --------
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
                      ("tombstones.json", tomb)):
        path = os.path.join(out_dir, name)
        blob = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(blob)
        raw = len(blob.encode("utf-8"))
        written[name] = {"bytes": raw,
                         "bytes_gzip": len(gzip.compress(blob.encode("utf-8"), 6))}

    return {
        "out_dir": os.path.relpath(out_dir, repo),
        "media_read": n,
        "written": written,
        "component_totals": totals,
        "evidence_class_totals": class_totals,
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
