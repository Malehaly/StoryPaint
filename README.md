# StoryPaint

**Storyboarding and animatics, connected between Blender and Krita.**

StoryPaint links Blender's Grease Pencil workflow with Krita's painting tools. Draw and stage your shots in Blender, send the Grease Pencil layers to Krita to finish the painting, then bring the finished artwork back into Blender as animated image planes — without manually exporting and importing every layer and frame.

StoryPaint is free and open source.

- [Repository](https://github.com/Malehaly/StoryPaint)
- [Releases](https://github.com/Malehaly/StoryPaint/releases)
- [Issue tracker](https://github.com/Malehaly/StoryPaint/issues)

## What StoryPaint does

### Blender → Krita

StoryPaint renders each Grease Pencil layer separately with a transparent background and sends the layers to Krita as paint layers.

- Layer names and stacking order are retained.
- Animated content keeps its frame timing.
- The Krita document is created automatically over a local connection — no files to manage.

### Krita → Blender

When the painting is ready, send it back from the StoryPaint docker, or right-click a layer or group in Krita's Layers docker and choose **Send back to Blender**.

StoryPaint brings the painted layers into Blender as camera-aligned image planes.

- The original Grease Pencil stays as your drawing reference.
- Layer position, rotation, scale and their keyframes are carried over.
- Re-sending an updated painting replaces the image on the existing plane, keeping its transforms and animation.

> **Note:** the return trip is image-based. It does not turn the painted result back into editable Grease Pencil strokes.

The two applications talk over a local socket on `localhost:65432`. Everything is transferred locally — no manual export or drag-and-drop.

## Storyboard tools in Blender

StoryPaint also adds tools for working with Grease Pencil and assembling shots:

- **TAB** toggles Object ↔ Draw mode.
- **Page Up / Page Down** switches Grease Pencil objects while staying in Draw mode.
- **Up / Down** switches the active Grease Pencil layer.
- **G / R / S** transform the active layer (not the whole object) in Draw mode.
- **Layer-transform auto-key** records layer transforms on the current frame with hold-style animation.
- **Dope Sheet grouping** keeps each layer's transform channels together.
- **Animated subtitles** for FONT objects, with SRT import/export, outline and camera attachment.
- **VSE frame-range sync** keeps scene strips in step with their scene's frame range.
- A **viewport playback** toggle for EEVEE temporal reprojection (prevents subtitle ghosting).
- A bundled **storyboard startup workspace**, loaded as a working copy.
- **Shot.000** scene asset in the StoryPaint catalog for the Video Sequencer.

## Shortcuts

| Key | Context | Action |
| --- | --- | --- |
| `TAB` | Grease Pencil | Toggle Object / Draw mode |
| `Page Up` / `Page Down` | Draw mode | Switch Grease Pencil objects |
| `↑` / `↓` | Dope Sheet / Sequencer / Grease Pencil | Switch active layer |
| `G` / `R` / `S` | Draw mode | Move / rotate / scale the active layer |
| `I` | Object mode, FONT object | Insert subtitle cue |
| Right-click object | Blender Outliner | Export Grease Pencil or image plane to Krita |
| Right-click layer or group | Krita Layers docker | Send back to Blender |

## Requirements

- **Blender 5.2 or newer**
- **Krita 5.x** with Python plugin support

Tested with Blender 5.2 and Krita 5.3.

## Installation

StoryPaint has two parts: a Blender extension and a Krita plugin. Install the Blender part first.

### 1. Blender extension

1. Download the Blender ZIP from the latest [release](https://github.com/Malehaly/StoryPaint/releases).
2. In Blender, open **Edit → Preferences → Get Extensions**.
3. Open the menu in the top-right and choose **Install from Disk**.
4. Select the StoryPaint Blender ZIP and install it. Enable StoryPaint if Blender doesn't do it automatically.

### 2. Krita plugin (assisted, from Blender)

1. Open the 3D Viewport sidebar with `N` and select the **StoryPaint** tab.
2. In the **Krita Side** section, click **Install Krita Side**.
3. In Krita, open **Settings → Configure Krita → Python Plugin Manager**, enable **StoryPaint**, then restart Krita.
4. Back in Blender, click **Check Krita Side**. When the connection is detected, the export controls unlock.

### Krita plugin (manual)

If the assisted install doesn't work, download the Krita ZIP from the same [release](https://github.com/Malehaly/StoryPaint/releases) and copy its `krita_bridge/` folder and `krita_bridge.desktop` file into Krita's `pykrita` directory:

- Windows: `%APPDATA%\krita\pykrita\`
- Linux: `~/.local/share/krita/pykrita/`
- macOS: `~/Library/Application Support/krita/pykrita/`

Then enable **StoryPaint** in Krita's Python Plugin Manager and restart Krita.

## Updating

Download the new Blender and Krita packages from the latest [release](https://github.com/Malehaly/StoryPaint/releases) and install them over the existing versions.

The Blender extension system can check for updates when StoryPaint is installed from a remote extension repository. Installing from a local ZIP does not add an update source by itself. After updating the Blender extension, check whether the Krita plugin also needs updating — the two are versioned and released together.

## Troubleshooting

**The Krita Side check does not connect**

- Make sure Krita is open.
- Check that StoryPaint is enabled in Krita's Python Plugin Manager.
- Restart Krita after enabling the plugin, then click **Check Krita Side** again.
- If it still fails, see the installation guide and the StoryPaint logs.

**The export controls are disabled**

Export unlocks once the Krita side is installed, enabled and connected. Finish the Krita installation first.

**The Krita plugin does not appear in the Plugin Manager**

Confirm that `krita_bridge/` and `krita_bridge.desktop` are inside Krita's `pykrita` directory, then restart Krita.

## Security notes

- The Blender ↔ Krita bridge is a local-only socket on `localhost:65432`. It
  serializes messages with `pickle` behind a fixed auth key, and is intended for
  trusted, single-user desktop use — it is never exposed to the network.
  Hardening the transport (for example, moving to JSON) is planned for a future
  release.
- [`krita-mcp/`](krita-mcp/) is a development-only code-execution server with no
  authentication; see its README before enabling it.
- A few modules under `core/` (`svg.py`, `package.py`, `manifest.py`,
  `hashes.py`) and `blender/svg_io.py` come from an earlier vector-transfer
  design and are not part of the current image-plane workflow. They are kept as
  legacy code in case vector transfers return.

## Contributing

Pull requests are welcome. For bugs and feature requests, [open an issue](https://github.com/Malehaly/StoryPaint/issues).

## Development tools

The repository also includes [`krita-mcp/`](krita-mcp/) — a small socket server
that lets you drive Krita from an external script or editor. It is used to test
the Krita side and is independent of the StoryPaint plugin.

## License

StoryPaint is licensed under **GPL-3.0-or-later**. See [LICENSE](LICENSE).

## Support the project

StoryPaint is free to use. If it helps your workflow and you'd like to support its development:

- [GitHub Sponsors](https://github.com/sponsors/Malehaly)
- [Ko-fi](https://ko-fi.com/malehaly)


