# LineUp Raster – Roadmap

Planned work and agreed design decisions. Nothing here is implemented yet.
Authors: Radu Andrei & Claude · Current version: 0.3.0

Order of work: **0.4 → 0.5 → 0.6 → 0.7**, then the ideas at the end. Each phase ships on its own and keeps the
principles of the plugin:

1. Your manual alignment is used as the starting point.
2. What you see in the window is what gets saved.
3. When an automatic step is unsure, it says why and leaves your work unchanged.

---

## 0.4 – Lens correction for DJI drones, plus manual correction

**Problem.** Wide-angle drone cameras bend straight lines (barrel distortion, the “sphere” effect), most visibly near
the edges. A photo with this distortion can't be placed correctly by moving, rotating and scaling alone.

**Design decisions**

- Lens correction is a property of the camera, so it is applied **once, before alignment**. Everything after it
  (comparison window, auto-refine, saving) works on the corrected photo.
- The original file is never modified. The correction is applied to the preview, to matching and to the saved GeoTIFF.

**Sources of the correction, tried in this order**

1. **DJI calibration in the photo.** Many DJI drones store factory-calibrated distortion coefficients in the image's
   XMP metadata (`drone-dji:DewarpData`: focal length, principal point, k1, k2, p1, p2, k3). If present, it is used
   automatically. If the photo was already dewarped in the drone (`DewarpFlag`), nothing more is applied.
2. **Manual.** For any photo:
   - a slider for the main curvature (k1, barrel ↔ pincushion);
   - a slider for the far edges (k2);
   - a **Show grid** overlay, so you can straighten a street you know is straight.

**Interface: a “Lens” panel above the comparison window**

- **Source:** Auto / From photo (DJI) / Manual / None.
- A status line showing what was found, for example `DJI FC3411 · calibration from XMP`.
- Sliders k1 and k2, **Show grid**, **Reset**.

**Output.** The saved GeoTIFF is resampled from the corrected photo. Metadata records that lens correction was applied
and with which values.

**Tests.** A synthetic photo with known distortion: corrected lines must be straight, and the coefficients read from a
DJI-style XMP block must match. Plus a real DJI sample when available.

---

## 0.5 – Visual comparison modes for spotting errors

**Problem.** The masking line shows one image or the other. Small offsets (a metre here, a degree there) are easy to
miss, especially away from the line.

**A “Compare” selector in the alignment window, with these modes**

| Mode | What you see | Why it helps |
|---|---|---|
| **Slider** | The current masking line | Familiar, good for a first look |
| **Red / cyan** | Reference in cyan, photo in red, both in greyscale, on top of each other | Where the images agree, details turn grey; any offset shows as red and cyan fringes along edges |
| **Edge tracing** | Outlines of the reference (roads, buildings) drawn as thin coloured lines over the photo | Reads like a CAD overlay or tracing paper; an offset shows as a line running beside its edge |
| **Checkerboard** | Alternating squares of reference and photo, adjustable size | Shows the whole image at once; errors appear as broken lines at square borders |
| **Blink** | Hold <kbd>Space</kbd> (or auto-blink 2–3 times per second) to switch between the images | The eye picks up anything that jumps, even a pixel or two |
| **Loupe** | A round magnifier under the cursor showing the other image, zoom 2–4× | Close inspection without leaving the overview |

**Automatic error map, after auto-refine**

- **Residual arrows** on each matched point, exaggerated (for example ×10), coloured green → red by size. Points that
  were rejected (for example rooftops) are shown in grey.
- **Misalignment heat map:** local shift between photo and reference, measured with dense optical flow, shown as a
  semi-transparent colour layer. Blue means aligned; yellow and red mark areas that are off. A legend gives the value
  in metres.
- A summary in the status line, for example: “median error 0.4 m · worst area 2.1 m (north-east corner)”.

**Order inside the phase:** red / cyan, blink and edge tracing first (cheap, no new dependencies); then checkerboard
and loupe; then the error map.

---

## 0.6 – Perspective and following the streets

**Two separate effects**

- **Camera tilt.** The photo isn't perfectly vertical, so the ground looks like a trapezoid. This is corrected with a
  **perspective (projective) model**: 8 parameters in place of the current 4. Works well on flat ground.
- **Leaning buildings (relief displacement).** Roofs shift outward from the photo centre, more for tall buildings and
  for those near the edges, and more with wide-angle lenses. The bases of buildings, streets, pavements and road
  markings stay in the right place. This lean can't be removed from a single photo without the height of every point
  (a digital surface model). The plugin places the ground correctly and leaves the lean visible.

**Planned features**

- **Placement model** selector for auto-refine: *Similarity* (current default) / *Perspective*.
- **Perspective mode** in manual alignment: four corner handles to drag, like “Distort” in image editors. The view can
  show it directly; Qt draws projective transforms.
- **Ground only** option: choose a line layer of streets from the project (for example OpenStreetMap). Matching then
  uses only features within a few metres of the streets. Rooftops are ignored, which matters in dense city centres.
- Rooftop matches that don't fit the ground plane are already rejected by RANSAC; with 0.5's residual arrows they become
  visible as grey points leaning outward.
- Saving uses the projective model (GDAL Warp with control points, order chosen to match).

**Documentation:** explain clearly what can and can't be corrected from one photo, and point to photogrammetry tools
(WebODM / OpenDroneMap, Agisoft Metashape) for true orthophotos from overlapping photos.

---

## 0.7 – Lens correction for any camera

Extends 0.4 beyond DJI.

1. **Camera profiles from Lensfun.** Lensfun is an open database of camera and lens profiles (distortion, plus
   vignetting and chromatic aberration). The plugin reads the camera make, model and focal length from EXIF and looks
   up the matching profile. The database files are XML; they are read directly and the correction is applied with
   OpenCV, so no new library is needed. Profiles are downloaded on request and cached; check the data licence before
   bundling any of them.
2. **Saved profiles.** **Save as profile for this camera** stores the current values (manual or estimated) keyed by
   camera make, model and focal length. The next photo from the same camera is corrected automatically.
3. **Estimate from the map.** After auto-refine there are hundreds of matched points between the photo and a flat
   reference. The map then works as a large calibration target: the distortion coefficients (and optionally focal length
   and principal point) can be computed, for example with OpenCV's camera calibration on the RANSAC ground inliers. This
   needs points spread to the edges of the photo; the plugin reports when there are too few.
4. **Fisheye lenses** (action cameras): a separate fisheye model, selectable in the Lens panel.

Final order of sources in the Lens panel: **Auto** = DJI XMP → saved profile → Lensfun → none; plus **Estimate from map**
and **Manual** at any time.

---

## Later ideas

- **Old maps and plans.**
  - Matching on structure (street network, intersections) against a drawn reference such as OpenStreetMap or a cadastral
    map.
  - An elastic transformation (thin plate spline) for paper shrinkage and drafting errors.
- **AI-assisted alignment through a QGIS MCP server.** A vision model proposes approximate landmark pairs: intersections,
  churches, squares, street names read from the plan. The plugin refines each pair locally, drops inconsistent ones, and
  you confirm them in the comparison window.
- **Polynomial / thin plate spline output** for photos and scans with local deformation.
- **Batch mode** for a series of photos from the same flight: reuse the lens profile and start each photo near the
  previous one.
- **Publication** in the official QGIS plugin repository.
- **Windows test** of `repair_dependencies.bat` on a clean QGIS install.
