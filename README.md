# LineUp Raster – QGIS plugin

Georeference aerial photos in QGIS: line the photo up over the map by hand in a before/after window, then let
feature matching (SIFT / ORB) snap it precisely into place. You see the result before it is saved.

**Authors:** Radu Andrei & Claude · **License:** MIT · **QGIS:** 3.16+ (tested on 3.34 and 3.40)

**[User guide (help site)](https://raduandrei-source.github.io/lineup-raster/)** ·
**[Installation](lineup_raster/INSTALLATION.md)** ·
**[Download](https://github.com/raduandrei-source/lineup-raster/releases)** ·
**[Roadmap](ROADMAP.md)**

---

## How it works

1. **Reference** – the current QGIS map view (satellite basemap, orthophoto, any layer) is rendered as a
   georeferenced reference image, sharper than the screen.
2. **Align by hand** – reference and photo sit on top of each other; a black masking line reveals one or the other.
   Move, zoom and rotate the photo until it roughly matches. **Compare** modes (red / cyan overlay, edge tracing,
   blink) make small offsets easy to see.
3. **Auto-refine** – starting from your alignment, feature matching finds hundreds of common points and moves the
   photo to the exact position, in the same window. Unreliable results are refused and your alignment is kept.
4. **Save** – a north-up GeoTIFF in the project CRS, placed by position, rotation and uniform scale, added to the map.

## Install

1. Download `lineup_raster.zip` from the
   [Releases page](https://github.com/raduandrei-source/lineup-raster/releases) and install it in QGIS:
   **Plugins → Manage and Install Plugins → Install from ZIP**.
2. With QGIS closed, install OpenCV into the QGIS Python:
   - **Windows:** double-click `repair_dependencies.bat` in the plugin folder, accept the administrator prompt.
   - **Debian / Ubuntu:** `sudo apt install python3-opencv`
   - **macOS / other:** run `install_dependencies.py` with the Python that QGIS uses.
3. Start QGIS: **Raster → LineUp Raster → Line up and georeference a photo…**.

Everything else – requirements, every platform, the rules for the QGIS Python (never upgrade its numpy) and
troubleshooting – is in **[INSTALLATION.md](lineup_raster/INSTALLATION.md)**.

## Repository layout

| Path | Content |
|---|---|
| `lineup_raster/` | The plugin (this folder is what goes into the QGIS plugins folder) |
| `lineup_raster/INSTALLATION.md` | Installation, dependencies, troubleshooting |
| `lineup_raster/PHILOSOPHY_AND_DEVELOPMENT.md` | Design decisions, development history, lessons learned |
| `ROADMAP.md` | Planned work: lens correction, more comparison modes and an error map, perspective, any-camera profiles |
| `docs/` | The help site, published with GitHub Pages |
| `tests/` | Automated tests that run in real QGIS (headless) |
| `.github/workflows/release.yml` | Publishes a release with the plugin zip when the version changes |

## Releases

Releases are automatic: when the `version=` line in `lineup_raster/metadata.txt` changes on `main`, the
[Release workflow](.github/workflows/release.yml) builds `lineup_raster.zip`, takes the release notes from the
changelog in `metadata.txt` and publishes release `v<version>`.

To build the zip by hand:

```
zip -r lineup_raster.zip lineup_raster -x "*/__pycache__/*"
```

The zip must contain the `lineup_raster` folder at its top level.

## Contributing

Bug reports and suggestions are welcome in [Issues](https://github.com/raduandrei-source/lineup-raster/issues).
For errors, please include the text from **View → Panels → Log Messages → LineUp Raster**.

## License

MIT – see [LICENSE](LICENSE). © 2026 Radu Andrei & Claude.
