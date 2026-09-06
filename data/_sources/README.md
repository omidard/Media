# `data/_sources/` — the raw upstream inputs

This directory is the **source cache**: the raw upstream payloads the builders read.
It is gitignored except for this file and `MANIFEST.json`, because the payloads are
large (MetaNetX alone is ~1.5 GB) and several carry non-commercial licences that make
redistribution a separate decision from use.

Populate it with:

```bash
python3 tools/fetch_sources.py --list     # what each source is and its licence
python3 tools/fetch_sources.py --all      # fetch everything that is public
python3 tools/fetch_sources.py mediadive --full   # ~3,300 medium records from the API
```

Point the builders at an existing cache instead with `MEDIA_SOURCES=/path/to/cache`.

## Why this directory exists

Nineteen generator scripts hardcoded a session scratchpad
(`/tmp/claude-1000/.../scratchpad/media_work`) that has been deleted, and not one of
the upstream payloads was ever committed. The result was that 98% of the shipped
catalogue had no runnable generator, and the mapping backbone itself
(`tools/bigg_metabolite_dict.json`) could not be rebuilt. Every tool now resolves its
inputs through `tools/mediapaths.py`, which reads this directory (or `$MEDIA_SOURCES`)
and fails loudly, naming the missing file and how to get it, instead of dying on a
path that no longer exists.

## `MANIFEST.json` — the recovery ledger

Committed on purpose. For each source it records the URL, the HTTP status actually
observed, the retrieval date, the byte count, the sha256 and the licence — and, for
the sources that cannot be re-acquired, `"status": "lost"` with the reason.

An absent input is recorded as absent. It is never implied to exist, and never
silently replaced by a default.

## What is recoverable, and what is not

| Source | Status | Licence |
|---|---|---|
| BiGG namespace | recoverable (public file) | BiGG Models, free for academic use |
| MetaNetX `chem_xref` / `chem_prop` | recoverable (public files) | CC BY 4.0 |
| USDA FoodData Central | recoverable (public zips) | US-government public domain |
| DSMZ MediaDive | recoverable (public REST API) | **CC BY 4.0 — attribution and licence notice required** |
| FooDB | recoverable (public dump) | **CC BY-NC 4.0 — non-commercial** |
| MediaDB (ISB) | recoverable by scrape (`tools/mediadb/fetch_mediadb.py`) | **All Rights Reserved** |
| HMDB | manual download (terms must be accepted) | **CC BY-NC 4.0 — non-commercial** |
| BMDB | manual download | see bovinedb.ca |
| Literature extractions (`lit/`) | **PERMANENTLY LOST** | n/a |
| GrowthDB handoffs (`growthdb/`) | **PERMANENTLY LOST** | n/a |

### The two lost sources, precisely

**`lit/extractions/batch_*.json`** produced 1,456 records (`lit_` 87, `growthlit_`
1,036, `complexlit_` 333). They were written by an LLM agent
(`tools/lit/lit_mining.js`) and deleted with the scratchpad. Re-running the miner does
not reproduce them: it yields *different* compositions that would be filed under the
*same* PMCIDs, DOIs and "verbatim proving snippet" fields — new content wearing the old
citations. The script now refuses to run without an explicit override for exactly that
reason. Those records are a frozen expert-curated snapshot and are corrected by stages
under `tools/stages/`, never by re-mining.

**`growthdb/media_to_add.json` and `growthdb/media_backmap.json`** were cross-session
handoffs in a second deleted scratchpad, and `tools/add_formulated_growthdb.py`
consumed its own input (it pops `medium.exchanges` from `growth_records.json`).
Measured today: 0 records remain eligible, so re-running it creates zero media.

## A rebuild is a source-version delta, not a reproduction

The upstream databases have moved since the original snapshot: the MediaDive fetch
recorded here returned 3,339 media where the corpus holds 3,148. So re-running a
builder produces a *different, newer* catalogue, not a reproduction of the shipped one.
That is a legitimate thing to want, but it must be reported as a version delta and
reviewed per class of change — never presented as evidence that the shipped data
reproduces.
