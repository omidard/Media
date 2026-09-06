#!/usr/bin/env python3
"""
Build the bulk / programmatic-access artifacts for the Media data API (v1).

Reads the canonical catalog (data/index.json) and the per-medium records
(data/media/<id>.json) and emits:

  into data/api/ — TRACKED, published by GitHub Pages
    manifest.json      - version, totals, file inventory, column schemas
    media.parquet      - one row per medium (summary + provenance)
    components.parquet - one row per (medium, component), tidy/long form

  into dist/api/ — NOT tracked, published as GitHub Release assets
    media.sqlite.gz        - SQLite db (media + components tables, indexed)
    media.jsonl.partNN.gz  - one full medium record per line (streamable)

WHY THE SPLIT
-------------
GitHub Pages serves this repository's root and refuses a published site over
1 GiB. The two JSONL shards and the SQLite database measured 83.9 + 64.8 + 24.1
= 172.8 MiB of DERIVED bulk — every byte of it a re-encoding of data/media,
which is itself published and must stay published because assets/media.js fetches
data/media/<id>.json at runtime. Keeping a second and third copy of the corpus
inside the published site spent a sixth of the budget on redundancy.

They are still built, by `make release-assets`, and still distributed — as
release assets, which is what a 170 MiB bulk download is for. Nothing became
unreachable: the parquet pair stays in the repository (5.7 MiB, and DuckDB can
query it straight over HTTP), every full record stays fetchable one at a time at
data/media/<id>.json, and pymediadb's iter_full_records() streams the release
when it is there and falls back to the per-medium endpoint when it is not. The
manifest names the download URL and the one command that fetches it.

Design notes
------------
* Driven off data/index.json so the exports contain exactly the published
  catalog (any un-indexed work-in-progress files under data/media/ are ignored).
* All large artifacts are gzipped to stay under GitHub's 100 MB per-file limit.
* Parquet is the primary surface for remote SQL (DuckDB can query it over HTTP).
* Cross-references are joined from data/refs.json, where stage 60 holds each
  distinct block once; the emitted columns are unchanged.
* No network, no non-stdlib deps beyond pyarrow (already used by the repo).

Rebuild:  python3 tools/build_api_exports.py          (repository artifacts)
          python3 tools/build_api_exports.py --bulk   (+ the release assets)
"""
import argparse
import os
import io
import gzip
import json
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq

import refs as REFS

API_VERSION = "v1"
BASE_URL = "https://omidard.github.io/Media"
RELEASE_TAG = "data-v1"
RELEASE_URL = "https://github.com/omidard/Media/releases/download/" + RELEASE_TAG

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "data")
MEDIA_DIR = os.path.join(DATA, "media")
OUT = os.path.join(DATA, "api")
BULK_OUT = os.path.join(REPO, "dist", "api")
os.makedirs(OUT, exist_ok=True)

_REFS = {"xrefs": {}, "notes": {}}

# Fixed xref columns surfaced as first-class fields in the components table.
XREF_KEYS = ["inchikey", "kegg", "chebi", "hmdb", "mnx", "seed", "biocyc"]

MEDIA_COLS = [
    "id", "name", "category", "organism_scope", "aerobic", "defined",
    "namespace", "source_type", "source_db",
    "n_components", "n_mapped", "n_in_biggr",
    "n_covered", "n_uncovered", "pct_covered",
    "citation", "doi", "url", "food_group",
    # --- added by the rebuild pass, so the bulk surface carries the same honest
    # fields as the catalog instead of only the legacy ones. A consumer reading
    # pct_covered alone was reading a number that counts invented components as
    # covered (COV-03 / PROV-07 / MEDIA-WEB-02).
    "source_id", "source_identity_evidence", "collection",
    "license", "commercial_use_ok", "attribution_required",
    "verification_status",
    "n_sourced", "n_derived", "n_observed", "n_unmappable",
    "pct_covered_source", "pct_covered_source_is_upper_bound",
    "pct_sourced_components_with_bigg_id",
    "name_display", "family", "n_with_concentration_mM",
    # The two ways a component fails to reach a BiGG exchange, and the model-input
    # twins, so a bulk consumer sees the same honest fields as the browser.
    "n_nonbigg_fallback", "n_no_exchange",
    "model_input_signature", "n_media_with_identical_model_input",
]
COMP_COLS = [
    "medium_id", "name", "bigg_metabolite", "exchange", "exchange_source",
    "lower_bound", "upper_bound", "concentration_mM",
    "in_biggr", "mapping_method", "mapping_confidence",
    # --- added by the rebuild pass. `mapping_confidence` alone said "exact" for a
    # name-string lookup; `evidence_tier` says what the identity was actually
    # decided on, `evidence_class` says whether the source stated the component at
    # all, and `source_name` is the string the mapping can be audited against.
    "evidence_tier", "evidence_class", "derived_class", "source_observed",
    "source_name", "target_name", "match_field", "match_key",
    "concentration_status", "concentration_source",
    "quantity_value", "quantity_value_verbatim",
    "quantity_unit", "quantity_basis", "derived_not_sourced",
] + ["xref_" + k for k in XREF_KEYS]


def _tally(values):
    out = {}
    for v in values:
        if v is None:
            continue
        out[v] = out.get(v, 0) + 1
    return out


def load_catalog():
    with open(os.path.join(DATA, "index.json")) as fh:
        return json.load(fh)


def iter_records(catalog):
    """Yield (catalog_summary, full_record) for every id in the catalog.

    The per-medium file is the source of truth for components; the catalog
    summary (data/index.json) is the source of truth for derived medium-level
    fields such as ``source_db`` (which is NOT stored on the per-medium file).
    """
    for summary in catalog["media"]:
        mid = summary["id"]
        path = os.path.join(MEDIA_DIR, mid + ".json")
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            yield summary, json.load(fh)


def _as_nullable_bool(v):
    """Normalize a defined/aerobic-style value to True/False/None.

    In the catalog, ``defined`` is mixed: real booleans for some sources and an
    empty string ('') where the concept doesn't apply -> map '' (and None) to null.
    """
    if isinstance(v, bool):
        return v
    if v in ("", None):
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "defined")
    return bool(v)


def medium_row(summary, rec):
    """One medium-level row: catalog summary fields + provenance from the record."""
    prov = rec.get("provenance", {}) or {}
    row = {
        "id": summary.get("id"),
        "name": summary.get("name"),
        "category": summary.get("category"),
        "organism_scope": summary.get("organism_scope"),
        "aerobic": _as_nullable_bool(summary.get("aerobic")),
        "defined": _as_nullable_bool(summary.get("defined")),
        "namespace": summary.get("namespace"),
        "source_type": summary.get("source_type") or prov.get("source_type"),
        "source_db": summary.get("source_db"),
        "n_components": summary.get("n_components"),
        "n_mapped": summary.get("n_mapped"),
        "n_in_biggr": summary.get("n_in_biggr"),
        "n_covered": (rec.get("coverage") or {}).get("n_covered"),
        "n_uncovered": (rec.get("coverage") or {}).get("n_uncovered"),
        "pct_covered": (rec.get("coverage") or {}).get("pct_covered"),
        "citation": summary.get("citation") or prov.get("citation"),
        "doi": prov.get("doi"),
        "url": prov.get("url"),
        "food_group": summary.get("food_group"),
        # verified source identity, licence and honest coverage — read from the
        # record where the stage chain wrote it, from the catalog where the catalog
        # is the authority. Absent stays null; nothing is defaulted.
        "source_id": summary.get("source_id"),
        "source_identity_evidence": summary.get("source_identity_evidence"),
        "collection": prov.get("collection"),
        "license": prov.get("license"),
        "commercial_use_ok": prov.get("commercial_use_ok"),
        "attribution_required": prov.get("attribution_required"),
        "verification_status": prov.get("verification_status"),
        "n_sourced": (rec.get("coverage_source") or {}).get("n_sourced"),
        "n_derived": rec.get("n_derived"),
        "n_observed": rec.get("n_observed"),
        "n_unmappable": rec.get("n_unmappable"),
        "pct_covered_source": (rec.get("coverage_source") or {}).get("pct_covered_source"),
        "pct_covered_source_is_upper_bound":
            (rec.get("coverage_source") or {}).get("pct_covered_source_is_upper_bound"),
        # Renamed from pct_covered_observed (2026-09-06): the old name read as
        # coverage of the medium while its denominator was the components the record
        # already carries. The catalog is the authority; the record read is the
        # fallback for a corpus written before the rename.
        "pct_sourced_components_with_bigg_id":
            summary.get("pct_sourced_components_with_bigg_id",
                        rec.get("pct_sourced_components_with_bigg_id",
                                rec.get("pct_covered_observed"))),
        "name_display": rec.get("name_display"),
        "family": (rec.get("family") or {}).get("id"),
        "n_with_concentration_mM": (rec.get("quantitation") or {}).get(
            "n_with_concentration_mM"),
        "n_nonbigg_fallback": summary.get("n_nonbigg_fallback"),
        "n_no_exchange": summary.get("n_no_exchange"),
        "model_input_signature": summary.get("model_input_signature"),
        "n_media_with_identical_model_input":
            summary.get("n_media_with_identical_model_input"),
    }
    return row


def _numeric_or_none(v):
    """The value when it is genuinely a number, else null. Never a parsed guess."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _text_or_none(v):
    """The value exactly as the source wrote it, as text."""
    return None if v is None else str(v)


def component_rows(mid, rec, refs=None):
    for c in rec.get("components", []) or []:
        # Cross-references are held once in data/refs.json and joined on
        # components[].xref_id (stage 60). The parquet/SQLite columns are
        # unchanged: a consumer still gets xref_inchikey, xref_kegg and the rest
        # as first-class fields.
        xref = REFS.component_xref(c, refs if refs is not None else _REFS)
        row = {
            "medium_id": mid,
            "name": c.get("name"),
            "bigg_metabolite": c.get("bigg_metabolite"),
            "exchange": c.get("exchange"),
            "exchange_source": c.get("exchange_source"),
            "lower_bound": c.get("lower_bound"),
            "upper_bound": c.get("upper_bound"),
            "concentration_mM": c.get("concentration_mM"),
            "in_biggr": c.get("in_biggr"),
            "mapping_method": c.get("mapping_method"),
            "mapping_confidence": c.get("mapping_confidence"),
            "evidence_tier": c.get("evidence_tier"),
            "evidence_class": c.get("evidence_class"),
            "derived_class": c.get("derived_class"),
            "source_observed": c.get("source_observed"),
            "source_name": c.get("source_name"),
            "target_name": c.get("target_name"),
            "match_field": c.get("match_field"),
            "match_key": c.get("match_key"),
            "concentration_status": c.get("concentration_status"),
            "concentration_source": c.get("concentration_source"),
            # Two columns, deliberately. 4,936 of the 353,581 source amounts are not
            # bare numbers -- they are the source's own string ("0.2 % (w/v)", "5 g/L",
            # "10 mM"), because the unit was never parsed out of the value. Coercing
            # them to a double would either invent a number or drop the measurement, so
            # quantity_value carries the numeric ones and quantity_value_verbatim
            # carries every one exactly as the source wrote it.
            "quantity_value": _numeric_or_none((c.get("quantity") or {}).get("value")),
            "quantity_value_verbatim": _text_or_none(
                (c.get("quantity") or {}).get("value")),
            "quantity_unit": (c.get("quantity") or {}).get("unit"),
            "quantity_basis": (c.get("quantity") or {}).get("basis"),
            "derived_not_sourced": c.get("derived_not_sourced"),
        }
        for k in XREF_KEYS:
            row["xref_" + k] = xref.get(k)
        yield row


def write_parquet(rows, cols, path):
    table = pa.Table.from_pydict(
        {col: [r.get(col) for r in rows] for col in cols}
    )
    pq.write_table(table, path, compression="zstd")
    return table.num_rows


def build_sqlite(media_rows, comp_rows, path_gz):
    tmp = os.path.join(OUT, "_media.sqlite")
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE media (%s)" % ", ".join("%s" % c for c in MEDIA_COLS)
    )
    cur.execute(
        "CREATE TABLE components (%s)" % ", ".join("%s" % c for c in COMP_COLS)
    )
    cur.executemany(
        "INSERT INTO media VALUES (%s)" % ",".join("?" * len(MEDIA_COLS)),
        [[r.get(c) for c in MEDIA_COLS] for r in media_rows],
    )
    cur.executemany(
        "INSERT INTO components VALUES (%s)" % ",".join("?" * len(COMP_COLS)),
        [[r.get(c) for c in COMP_COLS] for r in comp_rows],
    )
    cur.execute("CREATE INDEX ix_media_category ON media(category)")
    cur.execute("CREATE INDEX ix_media_source_db ON media(source_db)")
    cur.execute("CREATE INDEX ix_comp_medium ON components(medium_id)")
    cur.execute("CREATE INDEX ix_comp_exchange ON components(exchange)")
    cur.execute("CREATE INDEX ix_comp_bigg ON components(bigg_metabolite)")
    con.commit()
    con.close()
    with open(tmp, "rb") as fin, gzip.open(path_gz, "wb", compresslevel=9) as fout:
        fout.writelines(fin)
    os.remove(tmp)


# GitHub rejects any file over 100 MiB on push, and GitHub Pages serves this repo,
# so an artifact over the limit is not "large", it is unpublishable. The single
# media.jsonl.gz was 53.7 MB before this rebuild and 141.3 MB after it (the corrected
# corpus carries evidence tiers, licences, quantities and provenance on every record),
# which would have failed the push with no warning from this script. It is now written
# in shards under a declared budget, and the budget is ASSERTED rather than assumed.
MAX_ARTIFACT_BYTES = 90 * 1024 * 1024
SHARD_TARGET_BYTES = 80 * 1024 * 1024


def build_jsonl_shards(catalog, out_dir, stem="media.jsonl", target=SHARD_TARGET_BYTES):
    """Write <stem>.partNN.gz shards, none larger than `target`. Returns their names.

    Sharded on a size budget rather than on a fixed record count, because record size
    varies by two orders of magnitude across this corpus (a one-component glucose
    medium against a 300-component food record).
    """
    shards, part, fout, path = [], 0, None, None

    def _open():
        nonlocal part, fout, path
        part += 1
        path = os.path.join(out_dir, "%s.part%02d.gz" % (stem, part))
        fout = gzip.open(path, "wt", compresslevel=9)
        shards.append(os.path.basename(path))

    _open()
    for _summary, rec in iter_records(catalog):
        fout.write(json.dumps(rec, separators=(",", ":")))
        fout.write("\n")
        fout.flush()
        if os.path.getsize(path) >= target:
            fout.close()
            _open()
    fout.close()
    if os.path.getsize(path) == 0:                       # never ship an empty shard
        os.remove(path)
        shards.pop()
    return shards


def human(path):
    n = os.path.getsize(path)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f TB" % n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the MediaDB API exports.")
    ap.add_argument("--bulk", action="store_true",
                    help="also build the release assets (SQLite + JSONL shards) "
                         "into dist/api/. They are NOT tracked and NOT published "
                         "by GitHub Pages; upload them to the release.")
    ap.add_argument("--bulk-out", default=BULK_OUT,
                    help="where the release assets are written (default: dist/api)")
    args = ap.parse_args(argv)

    global _REFS
    try:
        _REFS = REFS.load_refs(REPO)
        print("refs: %d cross-reference blocks, %d notes"
              % (_REFS["n_xrefs"], _REFS["n_notes"]))
    except FileNotFoundError:
        print("refs: data/refs.json absent — reading cross-references inline "
              "(a corpus that has not been through stage 60)")

    catalog = load_catalog()
    print("catalog media:", catalog["count"])

    media_rows, comp_rows = [], []
    for summary, rec in iter_records(catalog):
        media_rows.append(medium_row(summary, rec))
        comp_rows.extend(component_rows(summary["id"], rec))
    print("loaded media rows:", len(media_rows), "component rows:", len(comp_rows))

    media_pq = os.path.join(OUT, "media.parquet")
    comp_pq = os.path.join(OUT, "components.parquet")

    write_parquet(media_rows, MEDIA_COLS, media_pq)
    write_parquet(comp_rows, COMP_COLS, comp_pq)

    files = {
        "media.parquet": {
            "rows": len(media_rows),
            "grain": "one row per medium",
            "columns": MEDIA_COLS,
        },
        "components.parquet": {
            "rows": len(comp_rows),
            "grain": "one row per (medium, component)",
            "columns": COMP_COLS,
        },
    }
    for name, meta in files.items():
        meta["size"] = human(os.path.join(OUT, name))

    # ---- the release assets: built on request, never into the published site ----
    bulk_dir = os.path.abspath(args.bulk_out)
    bulk = {}
    if args.bulk:
        os.makedirs(bulk_dir, exist_ok=True)
        sqlite_gz = os.path.join(bulk_dir, "media.sqlite.gz")
        build_sqlite(media_rows, comp_rows, sqlite_gz)
        shards = build_jsonl_shards(catalog, bulk_dir)
        bulk["media.sqlite.gz"] = {
            "tables": ["media", "components"],
            "note": "gunzip before opening; indexed on "
                    "category/source_db/medium_id/exchange/bigg_metabolite",
        }
        for i, sh in enumerate(shards, 1):
            bulk[sh] = {
                "grain": "one full medium record per line",
                "shard": i,
                "of_shards": len(shards),
                "note": "streamable; byte-for-byte the same schema as "
                        "data/media/<id>.json, so cross-references and notes are "
                        "keyed (xref_id / mapping_note_id / xref_note_id) and join "
                        "on data/refs.json, which stays in the repository. Sharded "
                        "because the single file would exceed GitHub's 100 MiB "
                        "per-file limit; concatenate the parts in name order to "
                        "reconstitute it.",
            }
        for name, meta in bulk.items():
            meta["size"] = human(os.path.join(bulk_dir, name))
        oversize = [(n, os.path.getsize(os.path.join(bulk_dir, n))) for n in bulk
                    if os.path.getsize(os.path.join(bulk_dir, n)) > MAX_ARTIFACT_BYTES]
        if oversize:
            raise SystemExit(
                "FATAL: %d release asset(s) exceed the %d MiB budget:\n%s"
                % (len(oversize), MAX_ARTIFACT_BYTES // (1024 * 1024),
                   "\n".join("  %s  %s" % (n, human(os.path.join(bulk_dir, n)))
                             for n, _ in oversize)))
        print("release assets -> %s" % os.path.relpath(bulk_dir, REPO))
        for name in sorted(bulk):
            print("  %-26s %s" % (name, bulk[name]["size"]))
        print("upload with:  gh release upload %s %s/* --clobber" % (RELEASE_TAG, bulk_dir))

    # The push-blocking check, run here rather than discovered by a failing push.
    # GitHub refuses any file over 100 MiB; this repo is also served by GitHub Pages.
    oversize = [(n, os.path.getsize(os.path.join(OUT, n))) for n in files
                if os.path.getsize(os.path.join(OUT, n)) > MAX_ARTIFACT_BYTES]
    stale = [f for f in os.listdir(OUT)
             if f not in files and f.endswith((".gz", ".parquet"))]
    if oversize:
        raise SystemExit(
            "FATAL: %d artifact(s) exceed the %d MiB budget and could not be pushed:\n%s"
            % (len(oversize), MAX_ARTIFACT_BYTES // (1024 * 1024),
               "\n".join("  %s  %s" % (n, human(os.path.join(OUT, n)))
                         for n, _ in oversize)))
    if stale:
        print("NOTE: %d file(s) in data/api are not part of this build and are left in "
              "place, not deleted: %s. The SQLite database and the JSONL shards moved "
              "to dist/api (`make release-assets`) and are distributed as release "
              "assets; delete the copies here." % (len(stale), ", ".join(sorted(stale))))

    manifest = {
        "api_version": API_VERSION,
        "base_url": BASE_URL,
        "catalog_count": catalog["count"],
        "component_records": len(comp_rows),
        "distinct_compounds": len({r["exchange"] for r in comp_rows if r.get("exchange")}),
        "coverage": {
            "by_exchange_source": _tally(r.get("exchange_source") for r in comp_rows),
            "total_uncovered": sum((m.get("n_uncovered") or 0) for m in media_rows),
            # `or 100` turned an absent measurement into a perfect score, so a medium
            # that was never measured counted as fully covered (SCHEMA-07 /
            # MEDIA-WEB-05). Null is now its own bucket and says so.
            "media_below_100pct_legacy": sum(
                1 for m in media_rows
                if m.get("pct_covered") is not None and m["pct_covered"] < 100),
            "media_with_no_legacy_coverage_measurement": sum(
                1 for m in media_rows if m.get("pct_covered") is None),
            "media_below_100pct_source_stated": sum(
                1 for m in media_rows
                if m.get("pct_covered_source") is not None
                and m["pct_covered_source"] < 100),
            "media_with_no_source_coverage_measurement": sum(
                1 for m in media_rows if m.get("pct_covered_source") is None),
            "definition": "pct_covered is the legacy metric and counts pipeline-derived "
                          "components as covered; pct_covered_source counts only "
                          "composition the cited source states. Null means not "
                          "measurable, never 100.",
        },
        # Where every component's exchange id landed, and how many media are
        # indistinguishable as a model input. Both are carried from the catalog so
        # a bulk consumer reads the same numbers the site states, with the same
        # definitions attached.
        "exchange_resolution": catalog.get("exchange_resolution", {}),
        "model_input_degeneracy": catalog.get("model_input_degeneracy", {}),
        "field_renames": catalog.get("field_renames", []),
        "components": {
            "n_records": len(comp_rows),
            "n_sourced": sum(1 for r in comp_rows if r.get("evidence_class") == "sourced"),
            "n_derived_not_sourced": sum(
                1 for r in comp_rows if r.get("evidence_class") == "derived"),
            "by_evidence_tier": _tally(r.get("evidence_tier") for r in comp_rows),
            "n_with_concentration_mM": sum(
                1 for r in comp_rows if r.get("concentration_mM") is not None),
        },
        "licensing": {
            "by_license": _tally(m.get("license") for m in media_rows),
            "n_commercial_use_ok": sum(1 for m in media_rows if m.get("commercial_use_ok")),
            "n_commercial_use_restricted": sum(
                1 for m in media_rows if m.get("commercial_use_ok") is False),
            "note": "records whose upstream licence forbids commercial use ship and are "
                    "labelled; see LICENSE and NOTICE for the per-source schedule.",
        },
        "by_category": catalog.get("by_category", {}),
        "by_source_db": catalog.get("by_source_db", {}),
        "endpoints": {
            "catalog": "/data/index.json",
            "medium": "/data/media/{id}.json",
            "reference_tables": "/data/refs.json",
            "component_stats": "/data/media_stats.json",
            "presence_matrix": "/data/presence_matrix.json",
            "bulk": {k: "/data/api/" + k for k in files},
            "manifest": "/data/api/manifest.json",
        },
        "bulk_files": files,
        # The two heaviest exports are DERIVED re-encodings of a corpus that is
        # itself published. Keeping them inside the published site spent 172.8 MiB
        # of GitHub Pages' 1 GiB budget on a second and third copy of data/media.
        # They are distributed, in full, as release assets.
        "bulk_download": {
            "where": "GitHub Release " + RELEASE_TAG,
            "url_prefix": RELEASE_URL,
            "files": (sorted(bulk) if bulk
                      else ["media.sqlite.gz", "media.jsonl.part01.gz",
                            "media.jsonl.part02.gz"]),
            "one_command": "gh release download %s --repo omidard/Media --pattern '*'"
                           % RELEASE_TAG,
            "without_gh": RELEASE_URL + "/media.sqlite.gz",
            "why_not_in_the_repository":
                "GitHub Pages publishes this repository's root and refuses a site "
                "over 1 GiB. These files are a re-encoding of data/media, which is "
                "published and stays published because the browser fetches "
                "data/media/{id}.json at runtime. Nothing here is unavailable: every "
                "full record is fetchable one at a time from the medium endpoint, "
                "the parquet pair is in the repository and queryable over HTTP with "
                "DuckDB, and pymediadb.iter_full_records() streams the release when "
                "it is present and falls back to the medium endpoint when it is not.",
            "rebuild": "make release-assets",
            "manifest": bulk or None,
        },
        "reference_tables": {
            "url": "/data/refs.json",
            "joins": {
                "components[].xref_id": "refs.xrefs[id] -> the cross-reference block",
                "components[].mapping_note_id": "refs.notes[id] -> the verbatim note",
                "components[].xref_note_id": "refs.notes[id] -> the verbatim note",
            },
            "why": "2,287 distinct cross-reference blocks were written out 665,582 "
                   "times and 113 distinct notes 621,274 times. They are held once. "
                   "An absent xref_id means the component has no cross-references. "
                   "The parquet and SQLite columns are unchanged: xref_inchikey, "
                   "xref_kegg and the rest are still first-class fields there.",
        },
        "notes": [
            "Read-only static API served by GitHub Pages with permissive CORS.",
            "Parquet files are queryable in place over HTTP with DuckDB.",
            "Bounds convention: lower_bound < 0 is uptake (mmol/gDW/h).",
            "Cross-references and prose notes are keyed; join /data/refs.json.",
        ],
    }
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)

    print("\nwrote data/api/:")
    for name in list(files) + ["manifest.json"]:
        print("  %-22s %s" % (name, human(os.path.join(OUT, name))))
    if not args.bulk:
        print("release assets (media.sqlite.gz, media.jsonl.part*.gz) not rebuilt; "
              "run `make release-assets` when the corpus changes.")


if __name__ == "__main__":
    main()
