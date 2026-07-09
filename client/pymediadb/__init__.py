"""
pymediadb - a tiny client for the Media data API.

The Media dataset (https://github.com/omidard/Media) is a curated, citation-backed
library of growth / simulation media, every component mapped to a standard BiGG
exchange reaction (``EX_<met>_e``) so any genome-scale model can adopt a medium.

It is served as static JSON/Parquet over GitHub Pages with permissive CORS, so this
client is a thin, dependency-light wrapper over plain HTTP GETs.

Quick start
-----------
    from pymediadb import MediaDB

    db = MediaDB()                       # points at the public GitHub Pages host
    cat = db.catalog()                   # full catalog summary (counts + media[])
    foods = db.list_media(category="food", defined=True)
    m = db.get_medium("m9_glucose_aerobic")
    medium = db.to_cobra_medium(m)       # {"EX_glc__D_e": -10.0, ...}
    # model.medium = medium              # drop straight into COBRApy

Bulk / analytics (needs pandas + pyarrow; duckdb optional):
    df = db.load_media()                 # DataFrame, one row per medium
    comp = db.load_components()          # DataFrame, one row per component
    db.query("SELECT category, count(*) FROM media GROUP BY category")  # duckdb
"""
from __future__ import annotations

import gzip
import json
import os
import time
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

__version__ = "1.0.0"

DEFAULT_BASE_URL = "https://omidard.github.io/Media"
_USER_AGENT = "pymediadb/%s (+https://github.com/omidard/Media)" % __version__


class MediaDB:
    """Read-only client for the Media data API (v1)."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Optional[str] = None,
        cache_ttl: float = 24 * 3600,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir or os.path.join(
            os.path.expanduser("~"), ".cache", "pymediadb"
        )
        self.cache_ttl = cache_ttl
        self._catalog: Optional[Dict[str, Any]] = None

    # ---- low-level fetch -------------------------------------------------

    def _url(self, path: str) -> str:
        return "%s/%s" % (self.base_url, path.lstrip("/"))

    def _cache_path(self, path: str) -> str:
        safe = path.strip("/").replace("/", "__")
        return os.path.join(self.cache_dir, safe)

    def _get_bytes(self, path: str, use_cache: bool = True) -> bytes:
        cp = self._cache_path(path)
        if use_cache and os.path.exists(cp):
            if self.cache_ttl <= 0 or (time.time() - os.path.getmtime(cp)) < self.cache_ttl:
                with open(cp, "rb") as fh:
                    return fh.read()
        req = urllib.request.Request(self._url(path), headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted host)
            data = resp.read()
        if use_cache:
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = cp + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, cp)
        return data

    def _get_json(self, path: str, use_cache: bool = True) -> Any:
        return json.loads(self._get_bytes(path, use_cache=use_cache))

    # ---- catalog + records ----------------------------------------------

    def manifest(self) -> Dict[str, Any]:
        """The API manifest: version, totals, and bulk-file inventory."""
        return self._get_json("data/api/manifest.json")

    def catalog(self, refresh: bool = False) -> Dict[str, Any]:
        """Full catalog: ``count``, ``by_category``, ``by_source_db``, ``media`` (summaries)."""
        if self._catalog is None or refresh:
            self._catalog = self._get_json("data/index.json", use_cache=not refresh)
        return self._catalog

    def list_media(
        self,
        category: Optional[str] = None,
        source_db: Optional[str] = None,
        defined: Optional[bool] = None,
        aerobic: Optional[bool] = None,
        organism_scope: Optional[str] = None,
        contains: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return catalog summaries filtered client-side. ``contains`` matches id/name substring."""
        out = []
        needle = contains.lower() if contains else None
        for m in self.catalog()["media"]:
            if category is not None and m.get("category") != category:
                continue
            if source_db is not None and m.get("source_db") != source_db:
                continue
            if defined is not None and bool(m.get("defined")) != defined:
                continue
            if aerobic is not None and bool(m.get("aerobic")) != aerobic:
                continue
            if organism_scope is not None and m.get("organism_scope") != organism_scope:
                continue
            if needle is not None and needle not in (
                (m.get("id", "") + " " + m.get("name", "")).lower()
            ):
                continue
            out.append(m)
        return out

    def ids(self, **filters: Any) -> List[str]:
        """Convenience: just the ids matching ``list_media`` filters."""
        return [m["id"] for m in self.list_media(**filters)]

    def get_medium(self, medium_id: str) -> Dict[str, Any]:
        """Full record for one medium (components, bounds, xrefs, provenance)."""
        return self._get_json("data/media/%s.json" % medium_id)

    def get_media(self, medium_ids: Iterable[str]) -> List[Dict[str, Any]]:
        return [self.get_medium(i) for i in medium_ids]

    # ---- model integration ----------------------------------------------

    @staticmethod
    def to_cobra_medium(
        record: Dict[str, Any],
        mapped_only: bool = True,
        uptake_only: bool = True,
    ) -> Dict[str, float]:
        """Build a COBRApy ``model.medium`` dict {exchange: |lower_bound|}.

        COBRApy expresses ``medium`` as positive uptake magnitudes keyed by
        exchange id. We take components whose ``lower_bound < 0`` (uptake).
        """
        medium: Dict[str, float] = {}
        for c in record.get("components", []) or []:
            ex = c.get("exchange")
            lb = c.get("lower_bound")
            if not ex or lb is None:
                continue
            if mapped_only and not c.get("bigg_metabolite"):
                continue
            if uptake_only and lb >= 0:
                continue
            medium[ex] = abs(float(lb))
        return medium

    # ---- bulk / analytics (optional heavier deps) -----------------------

    def _download_to(self, path: str, dest: str) -> str:
        data = self._get_bytes(path, use_cache=True)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        return dest

    def load_media(self):
        """One row per medium as a pandas DataFrame (reads media.parquet)."""
        import pandas as pd  # noqa: F401

        dest = os.path.join(self.cache_dir, "media.parquet")
        if not os.path.exists(dest):
            self._download_to("data/api/media.parquet", dest)
        return pd.read_parquet(dest)

    def load_components(self):
        """One row per (medium, component) as a pandas DataFrame (components.parquet)."""
        import pandas as pd  # noqa: F401

        dest = os.path.join(self.cache_dir, "components.parquet")
        if not os.path.exists(dest):
            self._download_to("data/api/components.parquet", dest)
        return pd.read_parquet(dest)

    def query(self, sql: str):
        """Run a DuckDB SQL query against the remote parquet files.

        Tables ``media`` and ``components`` are registered as views over the
        published parquet URLs (fetched lazily by DuckDB's httpfs).
        """
        import duckdb  # noqa: F401

        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(
            "CREATE VIEW media AS SELECT * FROM read_parquet('%s')"
            % self._url("data/api/media.parquet")
        )
        con.execute(
            "CREATE VIEW components AS SELECT * FROM read_parquet('%s')"
            % self._url("data/api/components.parquet")
        )
        return con.execute(sql).fetchdf()

    def iter_full_records(self):
        """Stream every full medium record from media.jsonl.gz (no full-index fetch)."""
        dest = os.path.join(self.cache_dir, "media.jsonl.gz")
        if not os.path.exists(dest):
            self._download_to("data/api/media.jsonl.gz", dest)
        with gzip.open(dest, "rt") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


__all__ = ["MediaDB", "__version__", "DEFAULT_BASE_URL"]
