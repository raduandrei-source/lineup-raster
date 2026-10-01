# Auto Georeference – philosophy, design and development history

For whoever takes over the project. It explains what the plugin does, why it is built this way, what worked,
what didn't, and what the author asked for along the way.

Authors: Radu Andrei & Claude · MIT License

---

## 1. The idea

Georeferencing an aerial photo by hand means placing dozens of control points between the photo and a map.
It is slow and tedious.

The plugin splits the work between person and computer:

- **The person** does the rough alignment: puts the photo approximately over the map (position, zoom, rotation).
  That takes a person a few seconds, while an algorithm struggles when the images differ a lot in scale,
  orientation or date.
- **The computer** does the fine alignment: starting from the person's alignment, it finds hundreds or thousands of
  common points (SIFT or ORB) and corrects the placement to below one pixel.

Three principles:

1. **The manual alignment is kept and used.** It is the starting point for automatic matching.
2. **What you see is what gets saved.** The automatic result appears in the same window before saving; it can be
   checked with the slider and undone.
3. **No result is better than a wrong result.** When the automatic matching is unsure, the plugin says why and
   keeps the manual alignment.

---

## 2. Workflow

1. In QGIS, show the area of interest (for example Google Satellite), as close as possible to the area of the photo.
2. `Raster → Auto Georeference → Auto Georeference Raster`, choose the photo.
3. The plugin renders the QGIS map view as a georeferenced reference, at a higher resolution than the screen
   (up to 3000 px) for a sharper image.
4. Alignment window: reference left of the black line, photo right of it. The user lines up the photo
   (move, zoom, rotate).
5. **Auto-refine alignment**: the plugin looks for common points starting from the manual alignment and moves the
   photo to the exact position. It reports how many points it found, the error and how much it corrected.
   **Undo** returns to the manual alignment.
6. **Save georeferenced photo…**: the photo is written as a north-up GeoTIFF with transparency in the corners and
   loaded into QGIS. The final message shows the pixel size (for example “0.3 m”) as a quick check of the scale.

Saving without auto-refine is possible; the georeference is then exactly the manual alignment.

---

## 3. The alignment window

- The two images sit **on top of each other**. **The black line is only a mask**: the left side shows the
  reference, the right side the photo. Moving the line moves no image.
- **Start: “match width”.** Both images are as wide as the window, with their proportions kept.
- **Independent move and zoom.** Left of the line you move / zoom the reference, right of it the photo.
  Zoom happens around the cursor.
- **Shift + drag / scroll** moves / zooms both images together, so the alignment stays the same. Useful for
  inspecting details.
- **Free pan and zoom at any zoom level.** Black shows where an image ends. The only limit: a 40 px strip of each
  image always stays on screen, so an image can't get lost.
- **Dead zone near the line:** within 15 px you grab the line, between 15 and 20 px nothing happens, beyond 20 px
  you move an image.
- Buttons: photo rotation in 0.1° steps; **Fit view** (brings everything back into the window, keeps the
  alignment); **Start over** (match width, alignment reset); photo opacity over the reference; colour sliders for
  each image (visual only).

---

## 4. How the code is organised

Everything is in `auto_georeference.py`:

| Component | Role |
|---|---|
| `ComparisonView` + `_ImageLayer` | The comparison view; each image has its own position (centre, zoom, rotation) |
| `AlignmentDialog` | The whole window with buttons, auto-refine and undo |
| `read_raster` | Reads any raster through GDAL (JPG, 16-bit TIFF, palette, greyscale) |
| `refine_alignment` | Automatic matching, starting from the manual alignment |
| `write_georeferenced` | Writes the final GeoTIFF (GDAL Warp, north-up) |
| `AutoGeoreferencePlugin` | QGIS integration: menu, reference rendering, saving |

**The view:** each image is drawn once over the whole window; the line only copies pieces of the two drawings.
Because of that, what is shown on each side is identical to the pixel wherever the line is, and dragging the line
is fast.

**Automatic matching (`refine_alignment`):**

1. The photo is warped with the manual alignment, so it has the same scale and orientation as the reference.
2. Both images get local contrast equalisation (CLAHE), which helps match old photos with satellite imagery.
3. **Guided matching:** a photo point may only be paired with reference points near the position the manual
   alignment gives it. Two passes: a wide radius (6% of the diagonal), then a narrow one (1.5%).
4. RANSAC with a **similarity model**: move + rotate + uniform scale, the same freedom the user has in the window.
   The photo is never sheared or stretched.
5. Safety checks: at least 12 points; points spread over the photo; compared with the manual alignment, scale
   within 20–25%, rotation within 10°, shift within 15% of the image. If any check fails, the manual alignment
   stays unchanged and the reason is shown.

**Saving:** the alignment in the window is converted into 5 control points, then `gdal.Warp` produces a regular
north-up GeoTIFF with an alpha band, compressed. A rotated geotransform is avoided because some programs don't
display it correctly.

**Libraries:** all rasters are read with plain GDAL `ReadRaster`/`WriteRaster` and wrapped in numpy, without
GDAL's numpy module (`gdal_array`), and `gdal.UseExceptions()` is not called (it also imports `gdal_array`).
Every GDAL result is checked explicitly. numpy and OpenCV are imported with a temporary stderr, so a missing or
mismatched library produces a clear message with instructions.

---

## 5. What didn't work, and why (lessons)

### 5.1 The masking slider

For several iterations the slider seemed to “drag” the photo. Each image was drawn starting from the position of
the line, so the image position depended on the line. Several patches were tried (separate pan, inverted
direction, limits, match width) without success. The fix was a different model: each image has its own position,
and the line is only a mask.

**Lesson:** when three or four fixes in a row don't solve a problem, the underlying model is wrong.

### 5.2 Georeferencing results unrelated to reality

Radu reported that, even after aligning carefully, the result had nothing to do with reality: wrong scale,
deformed image. Re-reading the code revealed several possible causes. Since it wasn't certain which one applied,
all of them were fixed:

1. **Deformation:** the final model was a full affine transform (6 parameters, with shear). With few or poor
   matches, shear and scale can take absurd values. The model is now a similarity and cannot deform.
2. **No check on the result:** whatever came out of RANSAC was saved, even an obviously wrong result. The result
   is now compared with the manual alignment and refused if it differs too much, and it is shown in the window
   before saving.
3. **JPEG EXIF rotation:** OpenCV automatically rotates JPEG photos that store an orientation in EXIF (common for
   drones and phones). GDAL and QGIS don't. Points were computed on a rotated image and applied to an unrotated one.
   Everything is now read with GDAL.
4. **Invisible result:** the user couldn't see what the algorithm had done before saving. Now it is visible.
5. **Weak reference:** the reference was a screen capture at screen resolution. It is now rendered by QGIS at a
   higher resolution.
6. **Pixel convention:** OpenCV counts coordinates from the centre of the first pixel, GDAL and Qt from its corner.
   The half-pixel difference was carried along uncorrected. It is now converted explicitly.
7. **Unguided matching:** matching searched for common points across the whole image. On repetitive textures
   (roofs, fields) it found many wrong pairs. It now searches only near the position given by the manual alignment.

### 5.3 “'NoneType' object has no attribute 'write'” on Windows

**Cause:** the first installation script ran `pip install --upgrade numpy`. That replaced the numpy shipped with
QGIS 3.40 with numpy 2. QGIS's GDAL is compiled for numpy 1, so its numpy module (`gdal_array`) could no longer
load. On Windows QGIS has no error output (`sys.stderr` is `None`): numpy crashed while trying to print its own
message, and the QGIS error window showed only that symptom.

Version 0.2.0 was the first to use `gdal_array`, in two places: `gdal.UseExceptions()` imports it automatically,
and pixels were read with `ReadAsArray`. That is why the error appeared only then.

**Fixed:**

- The plugin no longer uses `gdal_array` at all and works with any numpy version.
- OpenCV is imported safely; when it is missing or mismatched, the plugin shows the real reason and the fix.
- The installation scripts never upgrade numpy. `install_dependencies.py` repairs numpy only when GDAL cannot use
  it, and installs `opencv-python-headless==4.10.0.84` (compatible with numpy 1 and 2) with `--no-deps`.
- `repair_dependencies.bat` (Windows, QGIS closed) finds QGIS, asks for admin rights and runs the installer.

**Tested:** the Windows situation (numpy 2 over a GDAL built for numpy 1, no stderr, QGIS error window simulated)
was reproduced in QGIS: the old version shows the same error window; the new one runs the full workflow without
any error window. The installer was tested on a deliberately broken QGIS Python and on a healthy one, where it
changes nothing.

**Lesson:** a QGIS plugin should never upgrade libraries that ship with QGIS (numpy, GDAL, PyQt). Install only
what is missing, with fixed versions and `--no-deps`.

### 5.4 Other fixes

- **“Reset view” destroyed the alignment.** There is now **Fit view** (keeps the alignment) and **Start over**.
- **Shift + move at the edge of the screen** could put the two images out of step. The correction is now applied
  equally to both.
- **A rotated photo** was drawn slightly differently depending on the position of the line (a Qt rendering effect).
  It is now drawn once.
- **16-bit TIFF and palette rasters** are supported.

---

## 6. What worked – tested in real QGIS 3.34 (headless)

Test scenario:

- **Basemap:** synthetic, in **Stereo 70 (EPSG:3844)**, 0.5 m/pixel.
- **“Aerial photo”:** cut from the basemap at 0.3 m/pixel, rotated 17°, with different gamma and contrast,
  40 changed areas (new buildings), noise, JPEG compression and an EXIF orientation that would fool OpenCV.
- **Manual alignment:** deliberately inaccurate, 5% scale error, 3° rotation, about 50 px offset
  (115 px maximum error).

Results (29 checks, all passing):

- The rendered reference has a correct georeference and correct content.
- **Auto-refine: error below 1 pixel of the reference** (about 0.7 m here), with both SIFT (~1,000 points) and
  ORB (~3,200 points). Part of that error comes from how QGIS draws the test basemap.
- Wrong placement (photo put on another neighbourhood): auto-refine refuses and keeps the alignment.
- Full workflow from the menu: GeoTIFF saved, north-up, pixel 0.300 m (correct), CRS Stereo 70, lining up with the
  basemap almost as well as a perfect georeference.
- 16-bit single-band TIFF scan: works.
- Window: the line moves no image (pixel-identical, rotated photo included), free pan and zoom with black margins,
  Shift keeps the alignment, Fit view keeps the alignment.
- Auto-refine time (4000×3000 photo): ORB ~3 s, SIFT ~8 s.

**Not tested yet:** live Google Satellite (no internet in the test environment), real historical aerial photos,
`repair_dependencies.bat` on Windows.

The tests are in `tests/` in the repository.

---

## 7. Known limitations and ideas

- **Similarity only** (move, rotate, scale): perspective of oblique photos and relief are not corrected. Natural
  next step: a “projective / polynomial” option with `gdal.Warp` on many control points, also shown in the window.
- **Precision is limited by the reference resolution:** below one pixel of the reference. The closer the QGIS view
  is to the photo's area, the more precise the result.
- **Map rotation** in QGIS must be 0°.
- Very old photos compared with current satellite imagery: when a lot has changed, auto-refine may refuse. The
  manual alignment can still be saved.
- Idea: show the matched points over the image for visual confidence.
- **Old maps and plans:** the manual part already works. For automatic matching, a drawn reference
  (OpenStreetMap, cadastre) and structure-based matching (street network, intersections) would be needed, plus an
  elastic transformation (thin plate spline) for paper shrinkage and drafting errors. A promising direction is an
  AI-assisted workflow through a QGIS MCP server: a vision model proposes approximate landmark pairs (intersections,
  churches, squares, street names read from the plan), the plugin refines each one locally, inconsistent pairs are
  dropped and the user confirms in the comparison window.

---

## 8. Summary of the author's requests, in order

1. **“Give me all the files.”** The complete plugin.
2. **“Zoom and pan on reference and source no longer work.”** Wants to reposition and overlay the images.
3. **“Pan moves both, and a white band appears.”** Pan should move only the image under the cursor; between the
   images only the 1 px line.
4. **“Can you add a SIFT/ORB option?”** Plus a question about robustness to brightness and contrast.
5. **“The slider still doesn't work. Make the line black.”**
6. **“Pan works backwards.”**
7. **“The slider drags the whole source image. The images must stay fixed; the slider hides one and reveals the
   other.”** – the exact description of the real cause.
8. **“Is pan disabled near the slider?”** → dead zone.
9. **“Images one behind the other from the start, match width, no distortion. The slider must not move anything.”**
10. **“Clamp at the start, but on zoom out I want black margins.”**
11. **“A document for a colleague.”**
12. **“Masking still doesn't work. Rethink the whole strategy with fresh eyes.”** → comparison window rewritten
    on the right principle.
13. **“It works, but the georeferencing is garbage. Doesn't it use my overlay? Wrong scale, deformed image. And
    pan / zoom out at any zoom, with black where the image ends.”** → auto-refine visible in the window, starting
    from the manual overlay; no deformation; unreliable results refused; the fixes in 5.2; free pan and zoom; tests
    in real QGIS.
14. **Error in QGIS 3.40.1 on Windows: `AttributeError: 'NoneType' object has no attribute 'write'` from numpy.**
    → the cause in 5.3; the plugin works with any numpy and there is a repair script.
15. **Publish on GitHub, authors Radu Andrei & Claude, a complete installation guide, everything in English, and
    a help site.**

**In short:** line up the photo by hand in a before/after window where the images stay put. The computer must use
exactly that overlay to find the precise position. The result must be credible (correct scale, no deformation) and
visible before saving.
