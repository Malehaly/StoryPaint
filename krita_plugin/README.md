# StoryPaint — Krita plugin

Krita side of the bridge: receives Grease Pencil layers from Blender as paint
layers, and sends the finished painting back to Blender as image planes.

## Install

1. Copy the `krita_bridge/` folder into Krita's `pykrita` resources directory:
   - Windows: `%APPDATA%\krita\pykrita\`
   - Linux: `~/.local/share/krita/pykrita/`
   - macOS: `~/Library/Application Support/krita/pykrita/`
2. Copy `krita_bridge.desktop` into the same `pykrita/` directory.
3. Enable it in Krita: **Settings → Configure Krita → Python Plugin Manager**,
   tick **StoryPaint**, then restart Krita.

## Usage

- Start Blender, open a Grease Pencil scene, and run **Export GP to Krita**
  (N sidebar → "StoryPaint" tab, or right-click the object in the Outliner).
- The drawing opens in Krita as one paint layer per Blender layer.
- Paint, then press **Send back to Blender** in the StoryPaint docker
  (Settings → Dockers → StoryPaint if it isn't visible), or **right-click any
  layer / group** in the Layers docker and pick **Send back to Blender**.
- Back in Blender, the painting returns as camera-aligned image planes stacked
  over the original Grease Pencil.

The two applications talk over a local socket (`localhost:65432`) — no manual
file export/import.
