# The stage chain's input

`media_corpus_2026-09-06.tar.xz` is the **pre-remediation corpus**: the exact 13,515
records the correction stages under `tools/stages/` were written against, and the exact
bytes they consumed. 3.7 MB compressed, 443 MB expanded.

```bash
make baseline                              # expand + verify -> data/_rebuild/baseline/media
python3 tools/baseline.py --verify --deep  # digest-check the archive, extract nothing
python3 tools/baseline.py --check-history  # cross-check against this repo's own history
make reproduce                             # run the whole chain from it and diff the result
```

## Why it is committed

`make stages` is the build. The corpus in `data/media` is a frozen snapshot whose
generators are dead and whose raw inputs are gone (finding PIPE-01), so the chain of
transform stages is the only part of this resource that can be re-run — and a chain needs
an input.

Until this archive existed, that input was
`../media_curate_backups/data_media_20260906.tar.zst`: an untracked file on one machine.
`make stages` and `make stages-sample` were documented as runnable and both failed from a
clean checkout. That is PIPE-01 — a build step pointing at a path the repository does not
have — recreated one level up, inside the targets that exist to fix PIPE-01.

It is **not** `data/media`. `data/media` is what the chain *produces*, once `make promote`
has run. Feeding it back in is not a build: stage `10_normalize_schema` measured 906
non-BiGG fallbacks against 913 unmapped components and the chain aborted on its first
stage, because it was being handed its own output.

## What it is not

It is not a reproduction of the corpus from its upstream sources. Those inputs are gone;
see the `provenance` block of `data/MANIFEST.json` for the measured split between what is
re-fetchable in principle and the 1,456 records that are permanently unreproducible. This
archive makes the *corrections* reproducible, which is the reproducibility claim this
repository can honestly make.

## Format

`.tar.xz`, not `.tar.zst`: Python's standard library reads it (`tarfile` + `lzma`), so
expanding the chain's input needs no tool that is not already needed to run the chain. It
is written single-threaded at preset 6 with normalised member metadata (sorted names,
mtime 0, mode 0644, uid/gid 0, PAX), so rebuilding it from the same input reproduces the
same bytes — which is what makes `--verify` a check rather than a record of one machine's
run.

`BASELINE.json` carries the archive's sha256, the record count, and `corpus_sha256`: a
digest over the sorted `<filename> <sha256>` lines of the corpus itself, which identifies
the corpus independently of how it is packaged. It is what `--check-history` compares.
