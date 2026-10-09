#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
DGS_ROOT="${DGS_ROOT:-/mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset}"
mkdir -p "$DGS_ROOT/manifests"
# Fixed manifests are kept across retries. 24 candidates leave room for download/format failures.
for asset_type in models hdris; do
  manifest="$DGS_ROOT/manifests/$asset_type.expansion.json"
  if [[ ! -f "$manifest" ]]; then
    dgs-assets manifest --type "$asset_type" --limit 24 --seed 42 --resolution 2k --output "$manifest" --insecure
  fi
  # Continue to the other category even if some assets failed; rerun the same script to retry.
  dgs-assets download --manifest "$manifest" --root "$DGS_ROOT" --workers "${DGS_WORKERS:-4}" --insecure || true
done
dgs-people --provider renderpeople --root "$DGS_ROOT" --insecure || true
dgs-dataset inventory --root "$DGS_ROOT"
