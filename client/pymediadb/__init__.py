"""
pymediadb - a tiny client for the Media data API.

The Media dataset (https://github.com/omidard/Media) is a curated, citation-backed
library of growth / simulation media whose components carry a standard BiGG exchange
reaction (``EX_<met>_e``) so a genome-scale model can adopt a medium. 664,000 of
665,582 component records (99.8%) reach one; 1,364 carry a ModelSEED/MetaNetX/KEGG
fallback id that no BiGG model will accept, and 218 carry no exchange at all. Per
record: ``n_mapped``, ``n_nonbigg_fallback``, ``n_unmappable``.

Two further things a caller should know before trusting a result: the data is NOT
under a single licence (1,189 of 13,515 records may not be used commercially -- filter
on ``commercial_use_ok``), and 6,827 of 13,515 media (50.5%) hand a model a constraint
set identical to at least one other record (see ``n_media_with_identical_model_input``
in the catalog).

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
    for rec in db.iter_full_records(): ...   # streams every full record

Where the bytes live
--------------------
The parquet pair and every per-medium record are served from GitHub Pages. The
JSONL shards and the SQLite database are NOT: they are a second encoding of a
corpus that is already published, they measured 172.8 MB, and GitHub Pages
refuses a published site over 1 GiB.

**The hosted download of those two files does not exist yet.** The `data-v1`
release is planned, not published; ``data/api/manifest.json`` ->
``bulk_download.status`` is the authority, and this client reads it rather than
assuming. Build them yourself from a clone in the meantime:

    git clone https://github.com/omidard/Media && cd Media
    make release-assets            # -> dist/api/media.sqlite.gz, media.jsonl.part01.gz

``iter_full_records()`` streams the release when the manifest says it is
published, and walks the per-medium endpoint otherwise — including when the
release is advertised but a shard fails mid-stream. It yields every record
either way, and never raises because a download 404'd.

Cross-references and prose notes are held once in ``data/refs.json`` (2,287
distinct cross-reference blocks stood in for 665,582 copies) and joined on
``components[].xref_id`` / ``mapping_note_id`` / ``xref_note_id``.
``get_medium()`` and ``iter_full_records()`` perform the join by default; pass
``resolve=False`` for the record exactly as published.
"""
from __future__ import annotations

import gzip
import json
import os
import time
import urllib.request
import warnings
from typing import Any, Dict, Iterable, List, Optional

__version__ = "1.0.0"

DEFAULT_BASE_URL = "https://omidard.github.io/Media"
RELEASE_TAG = "data-v1"
RELEASE_URL = "https://github.com/omidard/Media/releases/download/" + RELEASE_TAG
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
        self._refs: Optional[Dict[str, Any]] = None

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

    def refs(self) -> Dict[str, Any]:
        """The cross-reference / note tables (``data/refs.json``).

        2,287 distinct cross-reference blocks were repeated across 665,582
        components and 113 distinct notes across 621,274 of them; holding them
        once is what keeps the published site under GitHub Pages' 1 GiB limit.
        Fetched once and cached; ``get_medium`` joins it for you.
        """
        if self._refs is None:
            self._refs = self._get_json("data/refs.json")
        return self._refs

    def get_medium(self, medium_id: str, resolve: bool = True) -> Dict[str, Any]:
        """Full record for one medium (components, bounds, xrefs, provenance).

        With ``resolve=True`` (the default) each component's ``xref_id`` /
        ``mapping_note_id`` / ``xref_note_id`` is joined against
        ``data/refs.json`` and the record comes back in its flat form, with
        ``xref``, ``target_xref``, ``mapping_note``, ``target_xref_note``,
        ``quantity_basis`` and the ``usda_*`` copies restored. Pass
        ``resolve=False`` for the record exactly as it is published.
        """
        rec = self._get_json("data/media/%s.json" % medium_id)
        return self.resolve_record(rec) if resolve else rec

    def resolve_record(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        """Join the reference tables into one published record."""
        refs = self.refs()
        xrefs, notes = refs.get("xrefs", {}), refs.get("notes", {})
        out = dict(rec)
        comps = []
        for c in rec.get("components") or []:
            c = dict(c)
            xid = c.pop("xref_id", None)
            if xid is not None:
                if xid not in xrefs:
                    raise KeyError(
                        "xref_id %r is not in data/refs.json; the record and the "
                        "reference table are out of step" % xid)
                c["xref"] = c["target_xref"] = xrefs[xid]
            elif "target_xref" not in c:
                c["xref"] = c["target_xref"] = {}
            for key, field in (("xref_note_id", "target_xref_note"),
                               ("mapping_note_id", "mapping_note")):
                nid = c.pop(key, None)
                if nid is not None:
                    if nid not in notes:
                        raise KeyError(
                            "%s %r is not in data/refs.json" % (key, nid))
                    c[field] = notes[nid]
            # quantity_basis / usda_amount / usda_unit / amount_basis were
            # type-exact copies of quantity.basis / .value / .unit / .basis on
            # every component that carried them, and are restored from there.
            q = c.get("quantity") or {}
            c.setdefault("quantity_basis", q.get("basis"))
            if c.get("amount_source") is not None:
                c.setdefault("usda_amount", q.get("value"))
                c.setdefault("usda_unit", q.get("unit"))
                c.setdefault("amount_basis", q.get("basis"))
            comps.append(c)
        out["components"] = comps
        return out

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

    def iter_full_records(self, resolve: bool = True):
        """Stream every full medium record.

        The bulk JSONL export is 148 MB of DERIVED bytes -- a second copy of a
        corpus that is already published one record at a time -- so it is not in
        the repository. GitHub Pages publishes the repository root and refuses a
        site over 1 GiB, and data/media has to stay published because the browser
        fetches it at runtime.

        The shards are meant to be assets on the ``data-v1`` release. That
        release is NOT published yet, and the manifest says so
        (``bulk_download.status``), so this method walks the per-medium endpoint
        instead. It also walks it when the release IS advertised and a shard
        turns out to be unreachable, resuming at the first record the shards did
        not deliver -- a fallback that raises is worse than no fallback, and a
        404 on a documented asset is exactly the case it exists for.

        Every record is yielded exactly once whichever path runs. ``resolve``
        joins data/refs.json as ``get_medium`` does.

        Build the same files yourself from a clone:
            make release-assets      # -> dist/api/
        """
        seen: set = set()
        try:
            shards = self._release_shards()
        except Exception as exc:                            # noqa: BLE001
            warnings.warn("could not read the bulk inventory from the manifest "
                          "(%s); streaming the per-medium endpoint instead" % exc,
                          RuntimeWarning, stacklevel=2)
            shards = []
        complete = bool(shards)
        for url in shards:
            try:
                dest = os.path.join(self.cache_dir, url.rsplit("/", 1)[-1])
                if not os.path.exists(dest):
                    self._download_url_to(url, dest)
                with gzip.open(dest, "rt") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        rec = json.loads(line)
                        rid = rec.get("id")
                        if rid in seen:
                            continue
                        seen.add(rid)
                        yield self.resolve_record(rec) if resolve else rec
            except Exception as exc:                        # noqa: BLE001
                # The advertised asset is missing, truncated or unreadable. Say so
                # -- silence here would look like a short corpus -- and finish from
                # the per-medium endpoint, which serves every record.
                warnings.warn("bulk shard %s is unreadable (%s); %d records "
                              "streamed from it, the rest come from the per-medium "
                              "endpoint" % (url, exc, len(seen)),
                              RuntimeWarning, stacklevel=2)
                complete = False
                break
        if complete:
            return
        # Every record is individually published, so walk the catalog for whatever
        # the shards did not deliver rather than failing.
        for m in self.catalog()["media"]:
            if m["id"] in seen:
                continue
            yield self.get_medium(m["id"], resolve=resolve)

    def bulk_download_status(self) -> str:
        """``published`` or ``planned`` -- whether the release assets exist.

        Read from the manifest the site publishes, not from a constant compiled
        into this client, so a client released before the assets were uploaded
        starts using them the moment they are.
        """
        bulk = (self.manifest().get("bulk_download") or {})
        return str(bulk.get("status") or "planned")

    def _release_shards(self) -> List[str]:
        """Absolute URLs of the JSONL shards, from the manifest's own inventory.

        Empty while ``bulk_download.status`` is not ``published``: the URLs are
        declared (that is where the assets will live) but fetching them would be
        a guaranteed 404, and a client should not spend a request proving what
        the manifest already told it.
        """
        man = self.manifest()
        bulk = man.get("bulk_download") or {}
        if str(bulk.get("status") or "planned") != "published":
            return []
        prefix = (bulk.get("url_prefix") or RELEASE_URL).rstrip("/")
        names = [n for n in (bulk.get("files") or []) if ".jsonl.part" in n]
        return ["%s/%s" % (prefix, n) for n in sorted(names)]

    def _download_url_to(self, url: str, dest: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req) as resp:           # noqa: S310
            data = resp.read()
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        tmp = dest + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
        return dest


__all__ = ["MediaDB", "__version__", "DEFAULT_BASE_URL", "RELEASE_TAG", "RELEASE_URL"]
