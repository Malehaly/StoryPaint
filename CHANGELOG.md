# Changelog

All notable changes to StoryPaint are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses `MAJOR.MINOR.PATCH` versioning.

## [1.1.0] - 2026-11-19

### Security

- Replaced the pickle wire protocol with JSON over `send_bytes`/`recv_bytes`
  (with a message-size cap and strict validation).
- Received messages are validated against a whitelist of message types with
  per-type field checks, type checks and collection-size caps (both sides).
- Replaced the fixed bridge auth key with a random, per-install key shared via
  a `bridge_key.json` file in the installed Krita plugin.
- The bridge listener is now **off by default**, toggled from the StoryPaint
  panel's **Bridge Connection** section, and it turns **OFF on every file open /
  new file** (the enable choice is per-session only).
- Removed the automatic `save_userpref()` call on add-on register.
- Removed the dev-only `krita_plugin/` fallback install path.

### Added

- "Save images inside" configuration: returned images are packed into the
  `.blend` by default, with an option to store them in a folder next to the
  `.blend` file.

### Changed

- External image storage now writes the **original compressed bytes** (folder
  size matches the packed `.blend` instead of re-encoding at low compression),
  and switching back to pack-in-blend deletes the external folder.
- Configuration title moved above the storage dropdown for readability.
- Export operators grey out in menus (e.g. the Outliner right-click) when the
  bridge is off.

## [1.0.1] - 2026-11-11

### Added

- Initial public release.
- Blender Extension and Krita plugin, distributed together.
- Blender → Krita Grease Pencil layer transfer (names, stacking order and frame timing preserved).
- Krita → Blender image-plane return workflow (camera-aligned, editable transforms and keyframes).
- Storyboard tools: GP draw-mode toggling, object/layer cycling, G/R/S layer transforms, layer-transform auto-key, Dope Sheet grouping.
- Animated subtitles with SRT import/export, outline and camera attachment.
- VSE scene-strip frame-range sync.
- EEVEE temporal-reprojection playback control.
- Bundled storyboard startup workspace and Shot.000 scene asset.
