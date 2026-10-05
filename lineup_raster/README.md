# LineUp Raster – QGIS plugin

Georeference aerial photos in two steps: line the photo up over the map by hand, then let feature matching
snap it precisely into place.

Authors: **Radu Andrei & Claude** · MIT License
Help site: https://raduandrei-source.github.io/lineup-raster/ ·
Installation: [INSTALLATION.md](INSTALLATION.md)

## What it does

- **Reference from the map.** The current QGIS map view (Google Satellite, an orthophoto, any layer) is rendered as a
  georeferenced reference image, sharper than the screen.
- **Before/after comparison window.** Reference and photo sit on top of each other; a black line reveals one or the
  other. Each image can be moved, zoomed and the photo rotated independently, so you can line them up by hand.
- **Compare modes for spotting errors.** Red / cyan overlay, edge tracing and blink show offsets of a pixel or two
  that are easy to miss with the slider.
- **Auto-refine.** Starting from your alignment, SIFT or ORB feature matching finds hundreds or thousands of common
  points and moves the photo to the exact position, in the same window, so you see the result before saving.
  Unreliable results are refused and your alignment is kept.
- **Save.** The photo is written as a north-up GeoTIFF with transparent corners, placed by position, rotation and
  uniform scale (the photo is never sheared or stretched), and added to the map.

## Quick start

1. Install the plugin zip from the [Releases page](https://github.com/raduandrei-source/lineup-raster/releases)
   (Plugins → Manage and Install Plugins → Install from ZIP).
2. Install OpenCV into the QGIS Python, with QGIS closed – Windows: double-click `repair_dependencies.bat`;
   Debian/Ubuntu: `sudo apt install python3-opencv`; details in [INSTALLATION.md](INSTALLATION.md).
3. In QGIS, show a satellite basemap, zoom to the area of the photo (map rotation 0°).
4. **Raster → LineUp Raster → Line up and georeference a photo…**, choose the photo.
5. Line the photo up, press **Auto-refine alignment**, check with the slider, **Save georeferenced photo…**.

**Raster → LineUp Raster → Help (online user guide)** opens the user guide in your browser.

## Controls in the alignment window

| Action | Effect |
|---|---|
| Drag the black line | Shows more of the reference (left) or the photo (right). The images stay where they are. |
| Drag on the left / right of the line | Moves the reference / the photo |
| Scroll | Zooms the image under the cursor, around the cursor |
| Shift + drag / scroll | Moves / zooms both images together (alignment kept) |
| Rotate photo slider | Rotates the photo around its centre, 0.1° steps |
| Fit view | Brings everything back into the window, alignment kept |
| Start over | Both images back to “match width”, rotation 0 |
| Photo over reference | Draws the photo semi-transparent over the reference side |
| Sat / Bright | Colour adjustments for your eyes only; matching is unaffected |
| Auto-refine alignment | Snaps the photo using SIFT or ORB, starting from your alignment |
| Undo auto-refine | Back to your alignment |
| Compare | Slider, Red / cyan overlay, Edge tracing or Blink (see below) |
| Hold <kbd>Space</kbd> | Shows the reference alone, in any mode |

Near the black line there is a small dead zone: within 15 px you grab the line, between 15 and 20 px nothing
happens, beyond 20 px you move an image.

## Compare modes

| Mode | What you see | How to read it |
|---|---|---|
| Slider | Reference left of the black line, photo right of it | Sweep the line across roads and building edges; they should continue without a jump |
| Red / cyan overlay | Reference in cyan, photo in red, both in grey tones with exposure evened out | Grey = the images agree. Red / cyan fringes along edges = offset. Solid red or cyan areas = something that exists only in the photo or only in the reference (new building, changed field) |
| Edge tracing | Your photo, with the outlines of the reference drawn over it in yellow | Yellow lines should sit on the edges of roads and buildings; a line running beside its edge shows the offset |
| Blink | The reference and the photo alternate about three times per second | Anything that jumps is out of place; the eye notices even a pixel or two |

In the overlay modes (red / cyan, edge tracing, blink) there is no black line: drag or scroll moves **the photo**,
**Shift** moves both images together, **Ctrl** moves the reference. Holding **Space** shows the reference alone in every
mode. The Compare modes only change how the images are shown; matching and saving are not affected.

## How auto-refine works

1. The photo is warped into the reference frame using your manual alignment.
2. Both images get local contrast equalisation (CLAHE); SIFT or ORB detects features.
3. Guided matching: a photo feature may only match reference features near the position your alignment gives it
   (two passes, 6% and then 1.5% of the image diagonal).
4. RANSAC with a similarity model (move + rotate + uniform scale).
5. Safety checks: at least 12 points, spread over the photo, and the result must stay close to your alignment
   (scale within about 20%, rotation within 10°, shift within 15% of the image). Otherwise the result is refused.
6. The final placement is written with `gdal.Warp` as a north-up GeoTIFF in the project CRS.

Precision is below one pixel of the reference in the automated tests. Zooming the QGIS map closer to the photo's area
makes the reference sharper and the result more precise.

## Limitations

- Position, rotation and uniform scale only: perspective of oblique photos and relief are not corrected.
- Map rotation in QGIS must be 0°.
- Very old photos compared with current imagery may have too little in common for auto-refine; the manual alignment
  can always be saved.

## More

- [INSTALLATION.md](INSTALLATION.md) – installation, dependencies, troubleshooting
- [PHILOSOPHY_AND_DEVELOPMENT.md](PHILOSOPHY_AND_DEVELOPMENT.md) – design decisions, development history, lessons learned
- Help site – https://raduandrei-source.github.io/lineup-raster/
