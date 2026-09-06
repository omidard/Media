# The MediaDB transform-stage contract

**Status:** authoritative. Every correction to the corpus is written as a stage that
obeys this contract. Read it before writing a stage; the runner enforces most of it
mechanically and will fail your stage if it does not comply.

## Why stages exist

`data/media/*.json` is the **sole surviving copy** of ~98% of this corpus. The original
builders hardcoded a `/tmp` scratchpad that has been deleted (audit finding PIPE-01), the
raw inputs were never in git, and 1,456 literature-derived media came from LLM extractions
whose batch files are gone. So corrections **cannot** be made by re-running the original
builders, and they must **not** be hand-patched into `data/media/*.json` — the institute's
standing rule is that every correction becomes a permanent, re-runnable pipeline step.

A stage therefore is: *a program that reads a corpus directory and writes a corrected
corpus directory.* The chain of stages, run in a fixed documented order, **is** the
pipeline that regenerates the corrected resource from the frozen snapshot.

```
data/_baseline/*.tar.xz         (the chain INPUT, committed; `make baseline`)
   |
   = data/_rebuild/baseline/media/   (READ-ONLY, never written by a stage)
   |
   +-> 00_baseline          -> data/_rebuild/stages/00_baseline/media/
   +-> 10_normalize_schema  -> data/_rebuild/stages/10_normalize_schema/media/
   +-> 2x_ ... 5x_          -> ...
   |
   = data/_rebuild/media/   (the corrected corpus; symlink/copy of the last stage)
   |
   +-> derived artifacts (index.json, coverage.json, api/, cluster/, stats, manifest)
```

**The chain's input is `data/_baseline`, not `data/media`.** `data/media` is what the
chain *produces*, once `make promote` has run. Feeding it back in is not a build:
`10_normalize_schema` counted 906 non-BiGG fallbacks against 913 unmapped components on
the promoted corpus and the chain aborted on its first stage. The pre-remediation corpus
— the exact bytes these stages were written against — is committed at
`data/_baseline/media_corpus_2026-09-06.tar.xz` (3.7 MB, 13,515 records), because before
it was, the chain's only input was an untracked archive on one machine and `make stages`
failed from a clone. See [data/_baseline/README.md](../../data/_baseline/README.md).

Promotion of `data/_rebuild/media/` over `data/media/` is a **separate, explicit,
backed-up step** (`make promote`). No stage ever promotes itself.

---

## 1. Where a stage lives, and what it is called

```
tools/stages/NN_snake_case_name.py
```

`NN` is a two-digit ordering prefix. **Ranges are reserved by workstream** so that four
agents can write stages concurrently without colliding:

| Range   | Workstream                                          | Owner              |
|---------|-----------------------------------------------------|--------------------|
| `00–09` | harness / baseline / provenance scaffold            | pipeline           |
| `10–19` | schema, types, null-vs-empty-vs-missing, counters    | pipeline           |
| `20–29` | licensing, source attribution, provenance segregation| licensing agent    |
| `30–39` | derived-not-sourced component labelling, coverage honesty | components agent |
| `40–49` | metabolite identity, mapping confidence tiers, xref provenance | chemistry agent |
| `50–59` | naming, grouping, display-facing record fields       | naming/web agent   |
| `60–89` | unassigned                                           | —                  |
| `90–99` | derived-artifact rebuild + manifest (NOT corpus stages) | pipeline        |

Pick the lowest free number in your range. If you need to run after another workstream,
say so in your registry entry (`after: [...]`) rather than renumbering someone else's stage.

## 2. Registration is mandatory

Every stage file must have a row in `tools/stages/stages.json`. An unregistered file in
`tools/stages/` is a **hard error** in the runner (`run_stages.py --check`), so a stage
can never be silently skipped — the exact silent-failure class this audit found everywhere.

Registry entry:

```json
{
  "id": "10_normalize_schema",
  "title": "Normalize record types, null-vs-empty drift, and record-level counters",
  "owner": "pipeline",
  "findings": ["SCHEMA-01", "SCHEMA-02", "SCHEMA-03", "SCHEMA-05", "SCHEMA-06", "SCHEMA-07"],
  "reads": ["corpus"],
  "writes": ["corpus"],
  "after": ["00_baseline"],
  "may_change_record_count": false,
  "may_change_id_set": false,
  "adds_keys": ["formulation_class", "provenance.transforms"],
  "removes_keys": [],
  "enabled": true
}
```

`adds_keys` / `removes_keys` are enforced: the runner diffs the key universe before and
after and fails on an undeclared change. Declaring a key you do not add is fine;
adding one you did not declare is not.

Two conveniences, because four agents write stages concurrently:

* **`"file"`** — a registry entry may name its script explicitly
  (`"file": "remap_components.py"`) when the filename does not carry the `NN_` prefix.
  A stage-shaped file that is neither `NN_`-named nor registered by `file` is a hard
  error, since the chain would never execute it.
* **`python3 tools/stages/run_stages.py --register-missing`** — writes a minimal,
  honest entry for every unregistered stage file it finds: owner inferred from the
  reserved range, findings scraped from the file's own `FINDINGS:` line, and
  `enabled` set from whether the script actually accepts `--in/--out`. It marks the
  entry `registered_by` the harness so you know to confirm it. Confirm your own
  entry rather than leaving the guess in place.

A registered stage may be `"enabled": false` with a `"disabled_reason"`. The runner
prints every disabled stage on each `--check` and each run, loudly, so a stage that
is not running is visible rather than merely absent.

## 3. Command-line contract

Every stage is executable and accepts exactly this interface:

```
python3 tools/stages/NN_name.py --in <corpus-dir> --out <corpus-dir> \
        [--report <path.json>] [--limit N] [--dry-run]
```

* `--in` and `--out` are **directories of per-medium JSON files** (`<id>.json`).
  Both are required; there are no defaults, so a stage can never accidentally
  write into `data/media/`.
* `--out` must contain **every** record from `--in`, changed or not (copy-through).
  Partial output is a defect, not an optimisation.
* `--report` is a JSON report (see §5). Defaults to `<out>/../report.json`.
* `--limit N` processes only the first N ids (sorted) — used for sample runs. With
  `--limit`, the stage still copies only those N records; the runner knows the run
  is a sample and relaxes count invariants accordingly.
* `--dry-run` computes and reports but writes no corpus.

`stagelib.run_stage()` gives you all of this for free — use it (§6).

If your stage predates part of this contract, the runner adapts rather than failing:
it reads your `--help` and passes only the flags you accept, recording in the chain
report that your report was not produced. `--in` and `--out` are the two it cannot
work without.

## 4. Hard rules for stage behaviour

1. **Never write to `--in`.** The runner opens the input read-only and re-hashes a
   sample after your stage to prove you did not mutate it.
2. **Absent is null.** Never write `""`, `0`, `false` or a guessed value to mean
   "not known". If you cannot determine a value, write `null` (or leave the key
   absent if the schema says the key is optional) and record the count in your report.
3. **A derived value must say it is derived.** If your stage computes a field from
   another field, it must also emit the method/evidence field next to it
   (`*_method`, `*_source`, `*_confidence`) so a reader can tell measurement from
   inference. A bare boolean or a bare number with no provenance is a contract breach.
4. **Every number needs its denominator.** Report counts as `{"n": x, "of": y}` in
   the report's `counters` block, not as a bare integer.
5. **Never key on an id prefix or a filename to decide chemistry or provenance.**
   Prefixes are allowed only for *routing* (which source-specific rule applies), never
   as evidence for a claim about the medium.
6. **Idempotent.** Running your stage on its own output must produce byte-identical
   output and `n_changed == 0`. The runner verifies this on the sample corpus, and
   the test suite verifies it in CI. If your stage appends to a list, guard the append.
7. **Fail loudly.** No bare `except:`. No `except Exception: pass`. No
   `x = d.get(k) or DEFAULT` where `DEFAULT` would be presented as a measurement.
   If an input record violates an assumption your stage relies on, raise — do not skip
   the record. A stage that silently skips is worse than a stage that dies.
8. **Stamp what you did.** Every record your stage *changes* gets an entry appended to
   `provenance.transforms` (`stagelib.stamp()` does this):
   ```json
   {"stage": "10_normalize_schema", "version": "1.0.0",
    "date": "2026-09-06", "changes": ["version:int->str", "n_mapped:recomputed"]}
   ```
   Records you did not change get no stamp.
9. **No network, no clock-dependence, no randomness** inside a corpus stage. Fetching
   belongs in `tools/fetch_sources.py`, which writes into `data/_sources/` under a
   manifest. A stage that needs external data reads it from a **committed** file under
   `tools/` or `data/_sources/`, and names that file in its report's `inputs`.
10. **Deterministic output bytes.** Write with
   `json.dump(obj, fh, indent=1, sort_keys=False, ensure_ascii=False)` via
   `stagelib.write_record()`, which also preserves key order so diffs stay readable.

## 5. The report (how a stage proves what it did)

Every run writes a JSON report. The runner aggregates these into
`data/_rebuild/report.json` and the build manifest. Shape:

```json
{
  "stage": "10_normalize_schema",
  "version": "1.0.0",
  "started_utc": "2026-09-06T06:40:00Z",
  "duration_s": 41.2,
  "sample": false,
  "in_dir": "data/media", "out_dir": "data/_rebuild/stages/10_normalize_schema/media",
  "n_in": 13515, "n_out": 13515, "n_changed": 13515,
  "inputs": ["tools/bigg_metabolite_dict.json"],
  "counters": {"version_coerced_int_to_str": {"n": 443, "of": 13515}},
  "assertions": [
    {"name": "n_mapped_equals_components_with_bigg", "passed": true,
     "observed": 664218, "expected": 664218}
  ],
  "unresolved": {"defined_still_null": {"n": 9798, "of": 13515,
                 "why": "no source stream asserted a value; guessing is forbidden"}},
  "errors": []
}
```

* `assertions` are your stage's **own** post-conditions — the things that must be true
  *because* your stage ran. At least one is required. `passed: false` ⇒ non-zero exit.
* `unresolved` is not optional book-keeping: it is how the resource stays honest about
  what it still does not know. If your stage leaves 9,798 nulls, say so here.

## 6. Writing a stage (skeleton)

```python
#!/usr/bin/env python3
"""One-paragraph contract: what this stage reads, writes, asserts, and which
findings it closes."""
from stagelib import run_stage, stamp, Report   # tools/stages is on sys.path

STAGE, VERSION = "30_label_derived_components", "1.0.0"

def transform(rec: dict, rep: Report) -> bool:
    """Mutate `rec` in place. Return True iff the record changed."""
    changed = []
    ...
    if changed:
        stamp(rec, STAGE, VERSION, changed)
        return True
    return False

def finalize(rep: Report) -> None:
    rep.assert_eq("derived_components_labelled",
                  rep.counters["labelled"]["n"], 229509)

if __name__ == "__main__":
    run_stage(STAGE, VERSION, transform, finalize=finalize,
              inputs=["tools/complex_ingredients.py"])
```

`run_stage` handles argv, IO, copy-through, determinism, the report, the provenance
stamp bookkeeping and the exit code. `Report` gives you `count(name, n, of)`,
`assert_eq/assert_true/assert_le`, `unresolved(name, n, of, why)`.

## 7. Test your stage on a SAMPLE first (required)

```
make sample                      # builds data/_rebuild/sample/media (400 media,
                                 # stratified across every id prefix + every category)
python3 tools/stages/run_stages.py --sample --only 30_label_derived_components
```

The sample run checks your stage for: copy-through completeness, idempotence
(runs it twice, compares bytes), input immutability, declared-key compliance and the
universal invariants. Only after the sample run is green should you run the full chain.

Add at least one test to `tests/test_stage_<yourstage>.py` that constructs a tiny
in-memory record exhibiting the defect, runs your `transform`, and asserts the corrected
shape — plus one asserting the defect **cannot silently return** (the regression test).

## 8. Universal invariants the runner checks after EVERY stage

These hold for the corpus at every point in the chain. They are in
`tools/stages/invariants.py`; each declares `enforced_from`, the stage after which it
must hold (some are currently violated by the frozen snapshot and only become
enforceable once the stage that fixes them has run).

| id  | invariant                                                              | enforced from |
|-----|------------------------------------------------------------------------|---------------|
| U1  | record count unchanged unless the stage declared `may_change_record_count` | always     |
| U2  | id set unchanged unless declared; `id` equals the filename stem          | always        |
| U3  | every file is a JSON object with the required top-level keys             | always        |
| U4  | for every component with non-null `bigg_metabolite`: `exchange == "EX_<met>_e"` | always |
| U5  | `n_components == len(components)`                                        | always        |
| U6  | no record gains a new empty-string value for a documented-nullable field | always        |
| U7  | top-level key universe changes only as declared                          | always        |
| U8  | `n_mapped == count(components with non-null bigg_metabolite)`            | 10_normalize_schema |
| U9  | `n_in_biggr == count(components with in_biggr true)`                     | always        |
| U10 | `version` is a string on every record                                    | 10_normalize_schema |
| U11 | `category` is in the declared enum                                       | 10_normalize_schema |

U4 is the load-bearing one for the chemistry workstream: it held in 664,218 of 664,218
components in the frozen snapshot, so any stage that rewrites a metabolite id must
rewrite the exchange in the same operation.

## 9. What a stage must NOT do

* must not delete records (segregate-and-label is the operator decision, for both
  non-commercial licensed records and pipeline-derived components);
* must not rewrite `data/media/`, `data/index.json` or anything under `data/api/`;
* must not "fix" a number by changing the number — fix the generator of the number;
* must not introduce a field the site will render as a claim without also introducing
  the field that says how the claim was reached.

## 10. Running the chain

```
make check          # registry ↔ filesystem consistency, no unregistered stages
make baseline       # expand + verify the chain input (data/_baseline)
make sample         # build the sample corpus, drawn from the chain input
make stages-sample  # run the full chain over the sample (fast, ~seconds)
make stages         # run the full chain over all 13,515 media -> data/_rebuild/media
make reproduce      # run the chain and compare the result to the shipped corpus
make test           # pytest: schema, invariants, regressions, harness
make derived        # rebuild index/coverage/api/cluster/stats/presence + MANIFEST
make verify         # re-run derived into a temp dir and diff against shipped
make promote        # backup data/media, then promote data/_rebuild/media over it
```

`make all` = `check → stages → test → derived`. It stops at the first failure and never
promotes.

## 11. After promotion: who owns a field

Once a stage takes over authorship of a field, the old generator must not silently
overwrite it. `tools/enrich_coverage.py` — which CI runs on every push — now refuses
to run over records carrying a `39_recompute_coverage` transform stamp, and says so:

```
REFUSING TO RUN: 5 of the first 5 records carry a coverage stamp from a transform
stage (39_recompute_coverage). Re-running this script would overwrite stage-produced
coverage with this file's older logic. Recompute coverage through the chain instead:
make stages
```

If your stage takes authorship of a field that an existing tool writes, add the same
guard to that tool (`COVERAGE_AUTHORITY_STAGES` is the pattern) in the same commit.
This is the two-layer clobber the audit warned about: builders and in-place curation
passes rewriting the same records in an order nothing recorded.

## 12. Evidence that the chain works

Run over the full corpus on 2026-09-06, six stages from four workstreams:

```
00_baseline              changed=0      assertions=9/9    invariants 8/8
10_normalize_schema      changed=13515  assertions=9/9    invariants 11/11
20_stamp_provenance      changed=13515  assertions=7/7    invariants 11/11
39_recompute_coverage    changed=13515  assertions=4/4    invariants 11/11
50_load_concentrations   changed=13515  assertions=12/12  invariants 11/11
51_normalize_names       changed=13515  assertions=11/11  invariants 11/11
final corpus -> data/_rebuild/media
```

Running the test suite against that corrected corpus
(`pytest --corpus data/_rebuild/media`) turns 9 of the 13 defect-ledger entries from
xfail to XPASS, which is the measurement that the corrections actually landed.
