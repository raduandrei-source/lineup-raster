# LineUp Raster – Installation and setup

Everything you need to install the plugin and get georeferencing working.
Authors: Radu Andrei & Claude · MIT License · Help site: https://raduandrei-source.github.io/lineup-raster/

---

## In short

1. Download `lineup_raster.zip` from the [Releases page](https://github.com/raduandrei-source/lineup-raster/releases).
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP** → choose the zip → **Install Plugin**.
3. Close QGIS and install OpenCV into the QGIS Python:
   - **Windows:** double-click `repair_dependencies.bat` in the plugin folder and accept the administrator prompt.
   - **Debian / Ubuntu:** `sudo apt install python3-opencv`
   - **macOS:** `/Applications/QGIS.app/Contents/MacOS/bin/python3 install_dependencies.py` (run from the plugin folder).
4. Start QGIS, open a satellite basemap, zoom to the area of your photo and use **Raster → LineUp Raster → Line up and georeference a photo…**.

The rest of this page explains each step, what can go wrong and how to fix it.

---

## 1. Requirements

| Component | Version | Where it comes from |
|---|---|---|
| QGIS | 3.16 or newer (tested on 3.34 and 3.40) | qgis.org |
| GDAL (Python bindings) | the one in QGIS | ships with QGIS |
| numpy | the one in QGIS | ships with QGIS – **never upgrade it** (see section 4) |
| OpenCV (`cv2`) with SIFT | 4.4 or newer; recommended `opencv-python-headless==4.10.0.84` | installed by you, once (section 3) |
| Internet | for online basemaps (Google Satellite, Esri, etc.) | – |

The plugin itself is pure Python; nothing needs compiling.

---

## 2. Install the plugin

### Option A – from the ZIP (recommended)

1. Download `lineup_raster.zip` from the [Releases page](https://github.com/raduandrei-source/lineup-raster/releases).
   Use the zip attached to a release. The green “Code → Download ZIP” button on GitHub gives the whole repository, which QGIS cannot install directly.
2. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP**, select the zip, **Install Plugin**.
3. Make sure **LineUp Raster** is ticked in the **Installed** tab.

### Option B – copy the folder by hand

1. In QGIS: **Settings → User Profiles → Open Active Profile Folder**, then open `python/plugins`
   (create the `plugins` folder if it is missing). Typical locations:
   - Windows: `C:\Users\<you>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins`
2. Copy the folder `lineup_raster` there. The folder name must stay exactly `lineup_raster`.
3. Restart QGIS and enable the plugin in **Plugins → Manage and Install Plugins → Installed**.

### Updating

**Coming from the earlier name “Auto Georeference”:** close QGIS and delete the old folder
`qgis_auto_georeference` from the plugins folder, then install LineUp Raster. Both would otherwise appear in the menu.


Close QGIS, delete the old `lineup_raster` folder from the plugins folder, then install the new version
(Option A or B). OpenCV stays installed; you don't need to repeat section 3.

---

## 3. Install OpenCV into the QGIS Python

QGIS has its own Python. OpenCV must be installed **into that Python**, with QGIS closed.

### Windows (QGIS installed with the standalone installer or OSGeo4W)

1. Close QGIS.
2. Open the plugin folder (see section 2, Option B) and double-click **`repair_dependencies.bat`**.
3. Accept the administrator prompt (QGIS lives in `Program Files`, so writing there needs admin rights).
4. Press a key when asked. At the end you should see a line like
   `[4/4] OK  numpy 1.26.4 | OpenCV 4.10.0 | GDAL 3.10.0` followed by `Done`.
5. Start QGIS.

The script finds QGIS in `Program Files`, loads the QGIS Python environment and runs `install_dependencies.py`, which:

- checks that QGIS's GDAL works with the installed numpy, and repairs numpy only if it doesn't;
- installs `opencv-python-headless==4.10.0.84` with `--no-deps`, so pip cannot replace numpy;
- skips anything that already works;
- prints a final check.

**If QGIS is installed somewhere else** (or the script can't find it): open the **OSGeo4W Shell** from the
Start menu (right-click → *Run as administrator*) and run

```
python "C:\Users\<you>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\lineup_raster\install_dependencies.py"
```

### Debian / Ubuntu (QGIS from apt)

```
sudo apt install python3-opencv
```

This OpenCV is built for the same numpy as QGIS and includes SIFT (OpenCV 4.5+). Don't use `pip` here: on recent
Ubuntu versions it refuses to write into the system Python (`externally-managed-environment`).

### Other Linux distributions, Flatpak, conda

Run the installer with the Python that QGIS uses:

```
python3 ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/lineup_raster/install_dependencies.py
```

For a conda / mamba QGIS environment: `conda install -c conda-forge opencv` inside that environment.

### macOS (official QGIS.app)

```
cd ~/Library/Application\ Support/QGIS/QGIS3/profiles/default/python/plugins/lineup_raster
/Applications/QGIS.app/Contents/MacOS/bin/python3 install_dependencies.py
```

The path to `python3` inside `QGIS.app` differs between QGIS builds. If it isn't there, look for a `python3`
inside `/Applications/QGIS.app/Contents/` (for example with Finder → *Show Package Contents*).

### Check that it worked

Open QGIS → **Plugins → Python Console** and type:

```python
import cv2, numpy; from osgeo import gdal_array; print(cv2.__version__, numpy.__version__)
```

Two version numbers and no error means everything is in place.

---

## 4. Rules for the QGIS Python (important)

- **Never run `pip install --upgrade numpy`** (or install packages that pull a newer numpy) in the QGIS Python.
  QGIS's GDAL is compiled for the numpy that ships with QGIS. Replacing numpy breaks GDAL and other QGIS tools,
  and on Windows the error message is lost: you only see
  `AttributeError: 'NoneType' object has no attribute 'write'` from numpy. `repair_dependencies.bat` fixes this.
- Install OpenCV with `--no-deps` and a fixed version: `pip install --no-deps opencv-python-headless==4.10.0.84`.
- Have only **one** OpenCV package installed. `opencv-python` and `opencv-python-headless` both provide `cv2`
  and conflict with each other. The installer removes the others.
- **On Windows, don't run pip from the QGIS Python Console.** There `sys.executable` is QGIS itself, so
  `subprocess.run([sys.executable, '-m', 'pip', ...])` starts another QGIS. Use the `.bat` file or the OSGeo4W Shell.
- Close QGIS before changing packages. On Windows, files of loaded packages are locked and pip fails halfway.

---

## 5. Prepare a QGIS project for georeferencing

1. **Add a satellite basemap.** In the **Browser** panel, right-click **XYZ Tiles → New Connection** and use, for example:
   - Google Satellite: `https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}`
   - Esri World Imagery: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`

   Respect the terms of use of the imagery provider.
   Any raster or vector layer shown on the map can serve as the reference: an orthophoto, a cadastral map, OpenStreetMap.
2. **Set the project CRS** to the system you want the result in (bottom-right corner of QGIS). The output GeoTIFF is
   written in the project CRS (for Romania, for example, Stereo 70 – EPSG:3844).
3. **Map rotation must be 0°** (the rotation box in the status bar).
4. **Zoom to the area of the photo** so it fills most of the map view, and wait until the basemap has finished
   loading. The plugin renders exactly what the map shows, at up to 3000 px. A closer view gives a sharper
   reference and a more precise result.

---

## 6. Use

1. **Raster → LineUp Raster → Line up and georeference a photo…**, choose the photo.
2. The alignment window opens: reference (map) left of the black line, your photo right of it.
   - Drag the black line to compare. The images stay where they are; the line only reveals one or the other.
   - Drag on an image to move it (left side = reference, right side = photo). Scroll to zoom the image under the cursor.
   - **Shift** + drag / scroll moves or zooms both images together and keeps the alignment.
   - Rotate the photo with the slider (0.1° steps). **Fit view** brings everything back into the window and keeps the
     alignment; **Start over** resets both images to “match width”.
   - **Compare** switches the view: *Red / cyan overlay* (grey where the images agree, coloured fringes where they
     don't), *Edge tracing* (reference outlines in yellow over your photo) or *Blink* (the images alternate).
     In these modes dragging moves the photo, Shift both images, Ctrl the reference.
   - Hold **Space** to see the reference alone, in any mode.
3. Line up the photo with the reference as well as you can.
4. Choose the detector (SIFT: more precise, ~8 s; ORB: faster, ~3 s) and press **Auto-refine alignment**.
   The photo snaps into place in the window. The status line shows how many points were matched and how much the
   alignment changed. Check it with the slider; **Undo auto-refine** returns to your alignment.
5. **Save georeferenced photo…** writes a north-up GeoTIFF exactly as shown and adds it to the map.
   The final message shows the photo’s pixel size (for example 0.3 m), a quick check that the scale makes sense.

You can also save without auto-refine; the photo is then placed exactly by your manual alignment.

The full guide is also in QGIS: **Raster → LineUp Raster → Help (online user guide)** opens the [help site](https://raduandrei-source.github.io/lineup-raster/).

---

## 7. Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| `AttributeError: 'NoneType' object has no attribute 'write'` (traceback in numpy) | numpy in the QGIS Python was replaced by a version GDAL can't use | Close QGIS, run `repair_dependencies.bat` (section 3) |
| “LineUp Raster – missing / mismatched library” | OpenCV is missing or doesn't match numpy | Section 3; the message shows the technical reason |
| Plugin missing from the Raster menu | Not enabled, or the folder has a different name | Plugins → Manage and Install Plugins → Installed → tick it; folder must be `lineup_raster` |
| “Please set the map rotation to 0°” | The map view is rotated | Set rotation to 0 in the status bar |
| The reference in the window is blank or partly empty | The basemap hadn't finished loading, or there is no internet | Wait until the map is fully drawn, then start the plugin again |
| “Auto-refine found no reliable result: the photo barely overlaps the reference” | The photo is placed outside the area shown on the map | Zoom the QGIS map to the photo's area, line the photo up first |
| “…only N reliable matching points” / “…all in one small area” | Too few features in common (very different dates, seasons, much changed land, water, forest) | Line up more carefully, try the other detector, zoom QGIS closer; or save your manual alignment |
| “…too different from your alignment (probably a wrong match)” | Automatic matching found something far from where you placed the photo | Check your alignment; the plugin refuses on purpose instead of guessing |
| Result is in the wrong place on the map | The project CRS differs from what you expected | Check the project CRS before starting; the GeoTIFF is written in it |
| Any other error | – | **View → Panels → Log Messages → “LineUp Raster”** shows the details; include them in an issue |

Report problems at https://github.com/raduandrei-source/lineup-raster/issues

---

## 8. Uninstall

QGIS → **Plugins → Manage and Install Plugins → Installed → LineUp Raster → Uninstall Plugin**.
To remove OpenCV as well (QGIS closed, admin shell): `python -m pip uninstall opencv-python-headless`
(or `sudo apt remove python3-opencv` on Debian/Ubuntu).

---

## 9. Tested on

- QGIS 3.34.4 on Ubuntu 24.04 (GDAL 3.8.4, numpy 1.26.4, OpenCV 4.6 and 4.10), automated tests in `tests/`
- QGIS 3.40.1 on Windows (used during development; `repair_dependencies.bat` itself has not been run on Windows yet)
- The “numpy replaced by numpy 2” situation was reproduced in QGIS and is handled by the plugin and by the installer.
