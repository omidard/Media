#!/usr/bin/env bash
# Run ONLY the naming/grouping/concentration stages (the 50-59 range), for
# iterating on this workstream without waiting for the whole chain.
#
# THE CANONICAL CHAIN IS tools/stages/run_stages.py. Use that for anything that
# ships: it enforces the registry, the universal invariants, input immutability
# and idempotence between every stage. This script is a development shortcut, and
# it deliberately does not promote anything.
#
# ORDER IS LOAD-BEARING. 50 must precede 51. concentration_mM is populated on
# 2.15% of components and 94.6% of lower bounds are exactly -1 or -1000, so a
# modifier named in a medium's title has nowhere to land; 23 of the 44 LB-family
# records are byte-identical in exchange set AND bounds AND concentration.
# Grouping names before the quantitative layer lands would merge records that are
# already indistinguishable and destroy the last evidence they ever differed.
#
# USAGE
#   bash tools/stages/run_chain.sh <OUT_DIR> [INPUT_CORPUS]
#
#   OUT_DIR         where the staged corpora and reports go. Never inside data/.
#   INPUT_CORPUS    defaults to data/media. Pass the output of an earlier stage
#                   (e.g. data/_rebuild/stages/40_remap_components/media) to run
#                   this workstream on top of another's.
#
# Optional environment:
#   MEDIADB_MASS_TABLE=<path.tsv>   the chemistry workstream's molar-mass table
#       (bigg_id / formula / molar_mass_g_per_mol / charge / mass_source). Without
#       it stage 50 falls back to the xref.formula already on 72.95% of components.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:?usage: run_chain.sh <OUT_DIR> [INPUT_CORPUS]}"
IN="${2:-$REPO/data/media}"

echo "== repo:  $REPO"
echo "== input: $IN"
echo "== out:   $OUT"

echo
echo "== regression tests first (a stage is not run before its tests pass) =="
python3 -m pytest "$REPO/tests/test_stage_naming.py" -q

echo
echo "== 50_load_concentrations =="
python3 "$REPO/tools/stages/50_load_concentrations.py" \
    --in "$IN" --out "$OUT/50_load_concentrations/media" \
    --report "$OUT/50_load_concentrations/report.json"

echo
echo "== 51_normalize_names =="
python3 "$REPO/tools/stages/51_normalize_names.py" \
    --in "$OUT/50_load_concentrations/media" \
    --out "$OUT/51_normalize_names/media" \
    --report "$OUT/51_normalize_names/report.json"

echo
echo "== corrected corpus: $OUT/51_normalize_names/media"
echo "== human-readable reports:"
ls -1 "$OUT/51_normalize_names/reports" 2>/dev/null || true
