#!/usr/bin/env python3
"""
Build the bulk / programmatic-access artifacts for the Media data API (v1).

Reads the canonical catalog (data/index.json) and the per-medium records
(data/media/<id>.json) and emits, into data/api/:

  manifest.json        - version, totals, file inventory, column schemas
  media.parquet        - one row per medium (summary + provenance)
  components.parquet    - one row per (medium, component), tidy/long form
  media.sqlite.gz      - SQLite db (media + components tables, indexed), gzipped
  media.jsonl.gz       - one full medium record per line, gzipped (streamable)

Design notes
------------
* Driven off data/index.json so the exports contain exactly the published
  catalog (any un-indexed work-in-progress files under data/media/ are ignored).
* All large artifacts are gzipped to stay under GitHub's 100 MB per-file limit.
* Parquet is the primary surface for remote SQL (DuckDB can query it over HTTP).
* No network, no non-stdlib deps beyond pyarrow (already used by the repo).

Rebuild:  python3 tools/build_api_exports.py
"""
import os
import io
import gzip
import json
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq

API_VERSION = "v1"
BASE_URL = "https://omidard.github.io/Media"

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "data")
MEDIA_DIR = os.path.join(DATA, "media")
OUT = os.path.join(DATA, "api")
os.makedirs(OUT, exist_ok=True)

# Fixed xref columns surfaced as first-class fields in the components table.
XREF_KEYS = ["inchikey", "kegg", "chebi", "hmdb", "mnx", "seed", "biocyc"]

MEDIA_COLS = [
    "id", "name", "category", "organism_scope", "aerobic", "defined",
    "namespace", "source_type", "source_db",
    "n_components", "n_mapped", "n_in_biggr",
    "citation", "doi", "url", "food_group",
]
COMP_COLS = [
    "medium_id", "name", "bigg_metabolite", "exchange",
    "lower_bound", "upper_bound", "concentration_mM",
    "in_biggr", "mapping_method", "mapping_confidence",
] + ["xref_" + k for k in XREF_KEYS]


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
        "citation": summary.get("citation") or prov.get("citation"),
        "doi": prov.get("doi"),
        "url": prov.get("url"),
        "food_group": summary.get("food_group"),
    }
    return row


def component_rows(mid, rec):
    for c in rec.get("components", []) or []:
        xref = c.get("xref", {}) or {}
        row = {
            "medium_id": mid,
            "name": c.get("name"),
            "bigg_metabolite": c.get("bigg_metabolite"),
            "exchange": c.get("exchange"),
            "lower_bound": c.get("lower_bound"),
            "upper_bound": c.get("upper_bound"),
            "concentration_mM": c.get("concentration_mM"),
            "in_biggr": c.get("in_biggr"),
            "mapping_method": c.get("mapping_method"),
            "mapping_confidence": c.get("mapping_confidence"),
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


def build_jsonl_gz(catalog, path_gz):
    with gzip.open(path_gz, "wt", compresslevel=9) as fout:
        for _summary, rec in iter_records(catalog):
            fout.write(json.dumps(rec, separators=(",", ":")))
            fout.write("\n")


def human(path):
    n = os.path.getsize(path)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f TB" % n


def main():
    catalog = load_catalog()
    print("catalog media:", catalog["count"])

    media_rows, comp_rows = [], []
    for summary, rec in iter_records(catalog):
        media_rows.append(medium_row(summary, rec))
        comp_rows.extend(component_rows(summary["id"], rec))
    print("loaded media rows:", len(media_rows), "component rows:", len(comp_rows))

    media_pq = os.path.join(OUT, "media.parquet")
    comp_pq = os.path.join(OUT, "components.parquet")
    sqlite_gz = os.path.join(OUT, "media.sqlite.gz")
    jsonl_gz = os.path.join(OUT, "media.jsonl.gz")

    write_parquet(media_rows, MEDIA_COLS, media_pq)
    write_parquet(comp_rows, COMP_COLS, comp_pq)
    build_sqlite(media_rows, comp_rows, sqlite_gz)
    build_jsonl_gz(catalog, jsonl_gz)

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
        "media.sqlite.gz": {
            "tables": ["media", "components"],
            "note": "gunzip before opening; indexed on category/source_db/medium_id/exchange/bigg_metabolite",
        },
        "media.jsonl.gz": {
            "rows": len(media_rows),
            "grain": "one full medium record per line",
            "note": "streamable; same schema as data/media/<id>.json",
        },
    }
    for name, meta in files.items():
        meta["size"] = human(os.path.join(OUT, name))

    manifest = {
        "api_version": API_VERSION,
        "base_url": BASE_URL,
        "catalog_count": catalog["count"],
        "component_records": len(comp_rows),
        "distinct_compounds": len({r["exchange"] for r in comp_rows if r.get("exchange")}),
        "by_category": catalog.get("by_category", {}),
        "by_source_db": catalog.get("by_source_db", {}),
        "endpoints": {
            "catalog": "/data/index.json",
            "medium": "/data/media/{id}.json",
            "component_stats": "/data/media_stats.json",
            "presence_matrix": "/data/presence_matrix.json",
            "bulk": {k: "/data/api/" + k for k in files},
            "manifest": "/data/api/manifest.json",
        },
        "bulk_files": files,
        "notes": [
            "Read-only static API served by GitHub Pages with permissive CORS.",
            "Parquet files are queryable in place over HTTP with DuckDB.",
            "Bounds convention: lower_bound < 0 is uptake (mmol/gDW/h).",
        ],
    }
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)

    print("\nwrote data/api/:")
    for name in list(files) + ["manifest.json"]:
        print("  %-22s %s" % (name, human(os.path.join(OUT, name))))


if __name__ == "__main__":
    main()
