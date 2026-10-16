# Free BlenderKit scene candidates

This independent command-line client follows the public search/download flow used by the official Blendkit client. It needs Python and an existing Blender executable, not the Blender add-on or a Sketchfab token. It tries anonymous access; if the service requires authentication, set `BLENDERKIT_API_KEY` locally.

```bash
git pull
pip install -e .
python scripts/download_blenderkit_scenes.py \
  --root "$PWD/dataset" \
  --blender /mnt/DataPart/jianghongda/tools/blender-4.5.3-linux-x64/blender \
  --limit 10 --max-download-mib 150
```

Use `--insecure` only if your server requires disabling TLS verification. Custom CAs are supported with `--ca-bundle PATH`.

The default search examines at most five pages (24 results/page), only free scenes, known file sizes <=150 MiB, and source Blender versions <=4.5. It counts already verified scenes toward the target of ten; this is not ten new scenes per rerun. `--pages 10` searches further. The size cap applies per downloaded file; packed output and total disk use can be larger. Results are candidates, not certified usable scene counts.

To list candidates without downloading:

```bash
python scripts/download_blenderkit_scenes.py --list-only --limit 10
```

Optional `--query 'interior'` restricts keywords. Scene identities use the provider's assetBaseId. Repeat runs verify and skip existing registered scenes. The script saves authors and licenses in `scene-source.json`, errors in `blenderkit-scenes-report.json`, and Blender load/dependency validation output in each scene's `validation.log`. It refuses registration on missing dependencies or failed Blender validation. It does not retain signed download URLs or tokens.

After download:

```bash
dgs-dataset inventory --root "$PWD/dataset"
dgs-dataset preview \
  --catalog "$PWD/dataset/catalog.json" \
  --output "$PWD/dataset/preview-blenderkit-plan.json" \
  --render-root "$PWD/dataset/renders/blenderkit-previews" --samples 16
dgs-dataset run \
  --plan "$PWD/dataset/preview-blenderkit-plan.json" \
  --blender /mnt/DataPart/jianghongda/tools/blender-4.5.3-linux-x64/blender \
  --gpus 0,1,2,3 --retry-incomplete
```

Check `dataset/renders/blenderkit-previews/index.html`. Preview currently includes all enabled catalog elements. Review placement, scale, full-trajectory clearance, texture quality and environment lighting. The current renderer replaces scene world lighting with the selected HDRI; this downloader does not change that behavior. Old render plans must be regenerated to remove disabled courtyard jobs. Existing courtyard training videos are not automatically removed from training data.
