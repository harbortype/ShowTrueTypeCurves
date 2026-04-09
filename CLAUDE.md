# Show TrueType Curves — Glyphs Plugin

## What this plugin does

A Glyphs reporter plugin (`com.harbortype.showTrueTypeCurves`) that overlays cubic-to-quadratic conversion results in real time while designing. It helps type designers preview how their PS (cubic) outlines will look after TTF export.

**Features:**
- **Draw outlines** — draws the converted quadratic paths in red in the background layer
- **Use variable font conversion** — uses `convertToCompatibleTrueTypeWithError_error_` instead of per-path `convertToQuadratic()` (slower, for variable fonts)
- **Use TrueType outlines for preview** — in hand/text tool mode, replaces the default PS fill with TT-converted paths + components
- **Find problematic TT conversions** — scans all glyphs, opens a tab with those exceeding the deviation threshold (`MAX_DEVIATION = 0.7`)

## Codebase structure

Single file plugin: `Show TrueType Curves.glyphsReporter/Contents/Resources/plugin.py`

Key constants at top of file:
- `DEFAULT_CURVE_ERROR = 0.6` — fallback for `TrueType Curve Error` custom parameter
- `MAX_DEVIATION = 0.7` — threshold for flagging a layer as problematic
- `NODE_RADIUS = 2.5` — display radius for off-curve node circles (unscaled)
- `DEVIATION_SAMPLES_PER_UNIT = 1` — sample density for deviation computation
- `DEVIATION_SAMPLES_MIN = 20` — floor sample count per segment

## Caching

`self.trueTypePathsCache` is a dict keyed by `(glyphName, layerId)`, storing `(lastOperation, paths, deviation_info)`. Cache is invalidated when `glyph.lastOperation()` changes, or when a setting is toggled.

## Deviation computation

`_computeLayerDeviation(layer, ttPaths)` matches each cubic PS segment to its corresponding TT quadratic segment(s) via shared on-curve endpoints, samples both, and computes max point-to-point distance. Returns `(value, point, normal_dir)`.

The label uses `offset = 20.0 / scale**0.5` for screen-space distance (see feedback memory on K/scale**0.5 pattern).

## Drawing hooks

- `background()` — draws TT curves + deviation label in edit mode (non-preview tools)
- `foreground()` / `inactiveLayerForeground()` — draws TT preview fill when hand/text tool is active
- Both delegate to `_drawTrueTypePreviewForLayer()` for the preview case

## Preferences (NSUserDefaults)

All prefs under `com.harbortype.showTrueTypeCurves.*`:
- `drawOutlines` (default: 1)
- `useVariableConversion` (default: 0)
- `useForPreview` (default: 0)

## Plugin metadata

- Bundle ID: `com.harbortype.showTrueTypeCurves`
- Principal class: `showTrueTypeCurves`
- Version: 1.5 (bundle version 8)
- Update feed: `https://raw.githubusercontent.com/harbortype/ShowTrueTypeCurves/main/...`
