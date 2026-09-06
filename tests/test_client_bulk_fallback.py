"""
pymediadb.iter_full_records() must never raise because the bulk download is missing.

The defect this pins, found by the independent verifier before the first push:

  The JSONL shards and the SQLite database left the repository (172.8 MiB, a
  second and third encoding of a corpus that is published one record at a time)
  and every document sent a reader to a `data-v1` GitHub Release that had never
  been created. `iter_full_records()` read the shard inventory from the manifest
  — which lists the files whether or not the release exists — and then called
  `_download_url_to()` OUTSIDE any try/except. The documented fallback ("falls
  back to the per-medium endpoint if the release is unreachable") therefore did
  not run: the generator raised HTTPError 404 on its first shard, for every user,
  from day one. A fallback that crashes is worse than no fallback, because the
  documentation promises it.

Three cases, each against a real HTTP server over a real (tiny) site:

  1. the release is not published (the state this repository ships in) — walk the
     per-medium endpoint, quietly, because nothing failed;
  2. the release is advertised and every asset 404s — the old crash; every record
     must still arrive, with a warning that says the fast path was unavailable;
  3. the release is advertised, the first shard is good and the second 404s — the
     union must be complete and free of duplicates, which is what makes resuming
     from the catalog correct rather than merely non-crashing.

No network: the "release" and the "site" are the same local server.
"""
import functools
import gzip
import http.server
import json
import os
import socketserver
import sys
import threading
import warnings

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "client"))

import pymediadb  # noqa: E402

N_RECORDS = 24
SHARD_SPLIT = 10          # records in the shard that works


def _record(i):
    return {
        "id": "medium_%02d" % i,
        "name": "Medium %02d" % i,
        "components": [{"name": "glucose", "exchange": "EX_glc__D_e",
                        "lower_bound": -10.0, "quantity": {"basis": "per_litre"}}],
    }


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """A miniature published site, plus a `bulk/` directory standing in for the release."""
    root = tmp_path_factory.mktemp("site")
    os.makedirs(root / "data" / "media")
    os.makedirs(root / "data" / "api")
    os.makedirs(root / "bulk")
    records = [_record(i) for i in range(N_RECORDS)]
    for rec in records:
        (root / "data" / "media" / (rec["id"] + ".json")).write_text(json.dumps(rec))
    (root / "data" / "index.json").write_text(json.dumps(
        {"count": N_RECORDS, "media": [{"id": r["id"], "name": r["name"]} for r in records]}))
    (root / "data" / "refs.json").write_text(json.dumps({"xrefs": {}, "notes": {}}))
    # part01 exists and holds the first SHARD_SPLIT records; part02 is never written,
    # so the server answers 404 for it — exactly what the real release does today.
    with gzip.open(root / "bulk" / "media.jsonl.part01.gz", "wt") as fh:
        for rec in records[:SHARD_SPLIT]:
            fh.write(json.dumps(rec) + "\n")
    return root


@pytest.fixture(scope="module")
def server(site):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(site))
    handler.log_message = lambda *a, **k: None            # noqa: ARG005 - quiet

    class Quiet(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

        def handle_error(self, request, client_address):  # noqa: ARG002
            pass

    httpd = Quiet(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _write_manifest(site, base, status, files):
    (site / "data" / "api" / "manifest.json").write_text(json.dumps({
        "api_version": "v1",
        "bulk_download": {
            "status": status,
            "url_prefix": base + "/bulk",
            "files": files,
        },
    }))


def _client(base, tmp_path):
    return pymediadb.MediaDB(base_url=base, cache_dir=str(tmp_path / "cache"),
                             cache_ttl=0)


def _ids(db):
    return [r["id"] for r in db.iter_full_records()]


def test_unpublished_release_streams_every_record_from_the_medium_endpoint(
        site, server, tmp_path):
    """The state this repository ships in: the release is planned, not published."""
    _write_manifest(site, server, "planned",
                    ["media.sqlite.gz", "media.jsonl.part01.gz"])
    db = _client(server, tmp_path)
    assert db.bulk_download_status() == "planned"
    assert db._release_shards() == [], (
        "a client must not spend requests on assets the manifest says do not exist")
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # nothing FAILED, so nothing may warn
        ids = _ids(db)
    assert ids == ["medium_%02d" % i for i in range(N_RECORDS)]


def test_advertised_release_that_404s_still_yields_every_record(site, server, tmp_path):
    """The crash, pinned: manifest says published, every asset is missing."""
    _write_manifest(site, server, "published",
                    ["media.sqlite.gz", "media.jsonl.part99.gz"])
    db = _client(server, tmp_path)
    assert db._release_shards() == [server + "/bulk/media.jsonl.part99.gz"]
    with pytest.warns(RuntimeWarning, match="unreadable"):
        ids = _ids(db)
    assert ids == ["medium_%02d" % i for i in range(N_RECORDS)], (
        "iter_full_records() must fall back to the per-medium endpoint instead of "
        "raising when a documented release asset is unreachable")


def test_partial_shard_failure_resumes_without_duplicates(site, server, tmp_path):
    """One shard works, the next 404s: the union is complete and each record is unique."""
    _write_manifest(site, server, "published",
                    ["media.jsonl.part01.gz", "media.jsonl.part02.gz"])
    db = _client(server, tmp_path)
    with pytest.warns(RuntimeWarning):
        ids = _ids(db)
    assert len(ids) == len(set(ids)), "records were yielded twice by the fallback"
    assert sorted(ids) == ["medium_%02d" % i for i in range(N_RECORDS)]


def test_unreadable_manifest_is_not_fatal(site, server, tmp_path):
    """A host whose manifest cannot be read still streams every record, loudly."""
    _write_manifest(site, server, "published", ["media.jsonl.part01.gz"])
    db = _client(server, tmp_path)

    def boom():
        raise OSError("manifest unreachable")

    db.manifest = boom                      # the inventory is the thing that fails
    with pytest.warns(RuntimeWarning, match="bulk inventory"):
        ids = _ids(db)
    assert sorted(ids) == ["medium_%02d" % i for i in range(N_RECORDS)]
