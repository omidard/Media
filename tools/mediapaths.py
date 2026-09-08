#!/usr/bin/env python3
"""
mediapaths — path resolution for every MediaDB tool.

WHY THIS EXISTS

Nineteen generator scripts hardcoded an absolute path into a session scratchpad
that has since been deleted (finding PIPE-01):

    /tmp/claude-1000/-data-.../eb8d91f3-.../scratchpad/media_work

Every one of them dies at import time, and they collectively generate 13,248 of
the 13,515 shipped media (98.0%). None of their inputs was ever committed. So the
shipped data/media/*.json is the only surviving copy of the corpus.

This module replaces those constants with three roots that are resolved from the
file's own location or from the environment, never from an absolute literal:

    REPO        the repository, derived from __file__
    SOURCES     raw upstream inputs        $MEDIA_SOURCES or <repo>/data/_sources
    OUT_ROOT    where a builder may write  $MEDIA_OUT     or <repo>/data/_rebuild/builders

THE OUTPUT ROOT IS NOT data/media, AND THAT IS DELIBERATE

A mechanical path fix would convert 19 scripts that safely CRASH into 19 scripts
that silently WRITE over the corpus — destroying the curation passes that were
applied on top of the builder output (enrich_coverage, apply_verification,
merge_duplicates, curate_names, curate_wellknown_media, remap_media_unmapped),
whose run order is recorded nowhere. So builders write to a staging tree, and
promotion into data/media is a separate, explicit, backed-up step.
`assert_not_frozen_corpus()` enforces that.

MISSING INPUTS FAIL LOUDLY AND SAY WHAT TO DO

`source_file()` raises MissingSource with the source's recovery status: public
(re-fetchable with tools/fetch_sources.py), or permanently lost (the literature
layer's LLM extraction batches). It never substitutes a default, and it never
lets a builder proceed on partial inputs.
"""
from __future__ import annotations

import os

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
DATA = os.path.join(REPO, "data")

#: The shipped corpus. READ-ONLY for every tool in this repo.
FROZEN_MEDIA = os.path.join(DATA, "media")

#: Raw upstream inputs, re-acquired by tools/fetch_sources.py.
SOURCES = os.path.abspath(os.environ.get("MEDIA_SOURCES", os.path.join(DATA, "_sources")))

#: Where builders write. Never data/media (see module docstring).
OUT_ROOT = os.path.abspath(os.environ.get("MEDIA_OUT",
                                          os.path.join(DATA, "_rebuild", "builders")))
OUT_MEDIA = os.path.join(OUT_ROOT, "media")


class MissingSource(FileNotFoundError):
    """A required raw input is absent. Always fatal — never defaulted around."""


# Recovery status per source tree, as established by the audit's verification pass.
# `public`: re-acquirable from a public endpoint. `lost`: no surviving input exists
# and re-running the generator would fabricate new content under the old citations.
SOURCE_INFO = {
    "mediadive": {"status": "public", "how": "python3 tools/fetch_sources.py mediadive",
                  "note": "DSMZ MediaDive REST API (CC BY 4.0). tools/mediadive/fetch_media.py "
                          "is checked in and is not path-poisoned."},
    "usda": {"status": "public", "how": "python3 tools/fetch_sources.py usda",
             "note": "USDA FoodData Central bulk zips; US-government public domain."},
    "foodb": {"status": "public", "how": "python3 tools/fetch_sources.py foodb",
              "note": "FooDB CSV dump, CC BY-NC 4.0: non-commercial; keep the licence "
                      "with the records it produces."},
    "mediadb": {"status": "public", "how": "python3 tools/fetch_sources.py mediadb",
                "note": "MediaDB (ISB) scrape via tools/mediadb/fetch_mediadb.py; "
                        "All Rights Reserved upstream."},
    "bigg": {"status": "public", "how": "python3 tools/fetch_sources.py bigg",
             "note": "bigg_models_metabolites.txt: the mapping backbone's input."},
    "metanetx": {"status": "public", "how": "python3 tools/fetch_sources.py metanetx",
                 "note": "MetaNetX chem_xref.tsv (CC BY 4.0)."},
    "hmdb": {"status": "public", "how": "python3 tools/fetch_sources.py hmdb",
             "note": "HMDB requires accepting its terms; CC BY-NC. Download by hand if "
                     "the automated fetch is refused."},
    "bmdb": {"status": "public", "how": "download the BMDB metabolite export by hand",
             "note": "Bovine Metabolome Database export (bmdb_metabolites.zip)."},
    "lit": {"status": "lost", "how": None,
            "note": "the literature layer (lit_ 87 + growthlit_ 1,036 + complexlit_ 333 = "
                    "1,456 media) came from LLM extraction batches written by "
                    "tools/lit/lit_mining.js into the deleted scratchpad. Re-running the "
                    "miner produces DIFFERENT extractions that would carry the SAME PMCIDs, "
                    "DOIs and 'verbatim proving snippet' fields as the shipped records — new "
                    "content wearing the old citations. Do not do it. These media are a "
                    "frozen snapshot; correct them with a transform stage instead."},
    "growthdb": {"status": "lost", "how": None,
                 "note": "the GrowthDB cross-session handoffs (media_to_add.json, "
                         "media_backmap.json) lived in a second deleted scratchpad, and "
                         "add_formulated_growthdb.py consumed its own input (0 records are "
                         "still eligible). Re-running produces zero media."},
}


def _info(first_part: str) -> dict:
    return SOURCE_INFO.get(first_part, {"status": "unknown", "how": None, "note": ""})


def source_path(*parts: str) -> str:
    """Absolute path under the sources root. Does not check existence."""
    return os.path.join(SOURCES, *parts)


def source_file(*parts: str, what: str | None = None) -> str:
    """Absolute path to a required raw input; raises MissingSource if it is absent."""
    p = source_path(*parts)
    if os.path.exists(p):
        return p
    info = _info(parts[0] if parts else "")
    lines = [
        "required input is missing: %s" % p,
        "  what:   %s" % (what or "/".join(parts)),
        "  status: %s" % info["status"],
    ]
    if info["note"]:
        lines.append("  note:   %s" % info["note"])
    if info["status"] == "public":
        lines.append("  fix:    %s   (or point $MEDIA_SOURCES at an existing cache)" % info["how"])
    elif info["status"] == "lost":
        lines.append("  fix:    none. This input cannot be re-acquired. Do not regenerate "
                     "these records; correct them with a stage under tools/stages/.")
    else:
        lines.append("  fix:    unknown source tree; see data/_sources/README.md")
    lines.append("  roots:  MEDIA_SOURCES=%s  MEDIA_OUT=%s" % (SOURCES, OUT_ROOT))
    raise MissingSource("\n".join(lines))


def source_dir(*parts: str, what: str | None = None) -> str:
    p = source_file(*parts, what=what)
    if not os.path.isdir(p):
        raise MissingSource("%s exists but is not a directory" % p)
    return p


def repo_file(*parts: str) -> str:
    """Absolute path to a committed file inside the repo (e.g. the BiGG dict)."""
    return os.path.join(REPO, *parts)


def assert_not_frozen_corpus(path: str) -> str:
    """Refuse to let a builder write into data/media."""
    if os.path.abspath(path).rstrip("/") == FROZEN_MEDIA.rstrip("/"):
        raise RuntimeError(
            "refusing to write to the frozen corpus %s.\n"
            "data/media is the sole surviving copy of the resource (PIPE-01) and the "
            "builder output is only the FIRST pass — the shipped records also carry "
            "curation applied afterwards, in an order no file records. Write to "
            "$MEDIA_OUT (%s) and promote deliberately with `make promote`."
            % (FROZEN_MEDIA, OUT_ROOT))
    return path


def out_media_dir(create: bool = True) -> str:
    """The staging directory a builder writes media into."""
    assert_not_frozen_corpus(OUT_MEDIA)
    if create:
        os.makedirs(OUT_MEDIA, exist_ok=True)
    return OUT_MEDIA


def describe() -> str:
    return ("REPO=%s\nSOURCES=%s (exists=%s)\nOUT_ROOT=%s\nFROZEN_MEDIA=%s (read-only)"
            % (REPO, SOURCES, os.path.isdir(SOURCES), OUT_ROOT, FROZEN_MEDIA))


if __name__ == "__main__":
    print(describe())
