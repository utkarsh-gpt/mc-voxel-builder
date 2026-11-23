#!/usr/bin/env bash
# Re-copy voxel models and reference photos, rebuild the catalogue, redeploy.
# Usage: ./sync.sh  (from viewer/)
# Optional: SYNC_NO_DEPLOY=1 to only refresh local files.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ART="${VOXEL_ART:-$ROOT/../pipeline/art}"
REFS_SRC="${VOXEL_REFS:-$ROOT/../pipeline/refs}"
SCOPE="${VERCEL_SCOPE:-utkarshgupta0122-4438s-projects}"
PROJECT="${VERCEL_PROJECT:-voxel-viewer}"

if [[ ! -d "$ART" ]]; then
  echo "art folder not found: $ART" >&2
  exit 1
fi

mkdir -p "$ROOT/models" "$ROOT/refs"
# Refresh models (json only).
find "$ROOT/models" -maxdepth 1 -type f -name '*.json' -delete
cp -a "$ART"/*.json "$ROOT/models/"
# Final passes (unique stems, e.g. windmill_voxels_textured.json).
if [[ -d "$ART/final" ]]; then
  shopt -s nullglob
  for f in "$ART"/final/*.json; do
    cp -a "$f" "$ROOT/models/"
  done
  shopt -u nullglob
fi

# Reference photos: subject stills + fal inputs, not masks.
find "$ROOT/refs" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' \) -delete
if [[ -d "$REFS_SRC" ]]; then
  shopt -s nullglob
  for f in "$REFS_SRC"/*.jpg "$REFS_SRC"/*_fal_in.png; do
    cp -a "$f" "$ROOT/refs/"
  done
  shopt -u nullglob
fi

# Vercel rejects files over 100 MB (e.g. the large landscape's 1/8-block "_fine" passes): skip them.
find "$ROOT/models" -maxdepth 1 -type f -name '*.json' -size +95M -print -delete | sed 's/^/skipped (over 95 MB): /'

python3 "$ROOT/scripts/generate_manifest.py"

if [[ "${SYNC_NO_DEPLOY:-}" == "1" ]]; then
  echo "Local files updated. Skipping deploy (SYNC_NO_DEPLOY=1)."
  exit 0
fi

exec vercel deploy "$ROOT" --prod --yes --project "$PROJECT" --scope "$SCOPE"
