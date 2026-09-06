#!/usr/bin/env bash
# Naming / grouping / concentration transform chain for the media corpus.
#
# WHY A CHAIN OF TRANSFORM STAGES AND NOT A REBUILD
# -------------------------------------------------
# The raw inputs are gone. 18 tools hardcode paths into a deleted /tmp scratchpad
# and data/media/*.json is the sole surviving copy of the corpus, so nothing here
# can be corrected by re-running an original builder. Every correction is instead
# a stage that READS the current corpus and WRITES a corrected corpus. The chain
# is idempotent, composable, and never edits data/media/ in place.
#
# ORDER IS LOAD-BEARING. Concentrations must land before names are grouped.
# 23 of the 44 LB-family records are byte-identical in exchange set AND bounds
# AND concentration, so grouping first would merge records that are already
# indistinguishable and destroy the last surviving evidence that they were ever
# different media -- their names.
#
# USAGE
#   bash tools/stages/run_chain.sh <OUT_DIR> [MASS_TABLE.tsv]
#
#   OUT_DIR      where the corrected corpus and reports are written. Never a
#                path inside data/.
#   MASS_TABLE   optional TSV from the mapping-layer stage:
#                  bigg_id  formula  molar_mass_g_per_mol  charge  mass_source
#                Without it the concentration stage falls back to the
#                xref.formula already present on 72.95% of components.
#
# OUTPUT
#   $OUT/01_concentrations/media/*.json     corpus + quantitative layer
#   $OUT/01_concentrations/reports/         concentrations_report.json, quantities.tsv
#   $OUT/02_names/media/*.json              corpus + family / modifier / collection layer
#   $OUT/02_names/reports/                  naming_report.json, families.tsv,
#                                           name_collisions.tsv,
#                                           composition_duplicates.tsv,
#                                           unnormalizable.tsv
#
# Each stage exits non-zero if any of its assertions fail, so the chain stops
# rather than shipping a corrected-looking corpus that violates its own contract.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:?usage: run_chain.sh <OUT_DIR> [MASS_TABLE.tsv]}"
MASS="${2:-}"

echo "== repo:   $REPO"
echo "== output: $OUT"

echo
echo "== stage 0: regression tests (run before any corpus is written) =="
python3 "$REPO/tools/stages/test_stages.py"

echo
echo "== stage 1: load_concentrations =="
if [ -n "$MASS" ]; then
  python3 "$REPO/tools/stages/load_concentrations.py" \
      --in "$REPO/data/media" --out "$OUT/01_concentrations" --mass-table "$MASS"
else
  echo "   (no mass table supplied; falling back to component xref.formula)"
  python3 "$REPO/tools/stages/load_concentrations.py" \
      --in "$REPO/data/media" --out "$OUT/01_concentrations"
fi

echo
echo "== stage 2: normalize_names =="
python3 "$REPO/tools/stages/normalize_names.py" \
    --in "$OUT/01_concentrations/media" --out "$OUT/02_names" \
    --vocab "$REPO/data/vocab"

echo
echo "== chain complete. Corrected corpus: $OUT/02_names/media"
echo "== reports:"
ls -1 "$OUT/01_concentrations/reports" "$OUT/02_names/reports"
