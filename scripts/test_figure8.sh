#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
DGS_ROOT="${DGS_ROOT:-/mnt/DataPart/jianghongda/related_work/Data-Generation-Server/dataset}"
DGS_BLENDER="${DGS_BLENDER:-/mnt/DataPart/jianghongda/tools/blender-4.5.3-linux-x64/blender}"
DGS_HDRI=$(python - "$DGS_ROOT" <<'PY'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
for metadata in sorted(root.glob('hdris/polyhaven/*/asset.json')):
    data = json.loads(metadata.read_text())
    for record in data['files']:
        file = metadata.parent / record['path']
        if file.suffix.lower() in ('.hdr', '.exr') and file.is_file():
            print(file.resolve())
            raise SystemExit(0)
raise SystemExit('No downloaded HDRI found in dataset/hdris/polyhaven')
PY
)
CUDA_VISIBLE_DEVICES="${DGS_GPU:-3}" dgs-render \
  --root "$DGS_ROOT" --blender "$DGS_BLENDER" \
  --model-id chinese_cabinet --hdri "$DGS_HDRI" \
  --environment courtyard --trajectory figure8 \
  --theta "${DGS_THETA:-30}" --phi "${DGS_PHI:-5}" \
  --frames 121 --width 1280 --height 720 \
  --orientation "${DGS_ORIENTATION:-random}" --seed "${DGS_SEED:-42}" \
  --samples 32 \
  --output "${DGS_OUTPUT:-$DGS_ROOT/renders/cabinet_figure8_121}"
