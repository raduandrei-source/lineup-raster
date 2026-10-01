# Tests

Automated tests that run the plugin inside real QGIS, without a screen (Qt offscreen).
Authors: Radu Andrei & Claude · MIT License

Tested environment: Ubuntu 24.04, QGIS 3.34 (`apt install python3-qgis qgis-providers python3-gdal python3-opencv`),
run with the system Python (`/usr/bin/python3.12`).

| File | What it checks |
|---|---|
| `qgis_integration_test.py` | Renders a reference from a synthetic Stereo 70 basemap, builds a rotated, rescaled, altered “aerial photo” (with an EXIF orientation trap), aligns it roughly, runs auto-refine with SIFT and ORB, checks the result against the ground truth, runs the full `run()` workflow, checks the saved GeoTIFF, and checks the comparison window (masking line, pan, zoom, Shift, Fit view). |
| `numpy2_mismatch_test.py` | Reproduces the Windows failure (numpy 2 installed over a GDAL built for numpy 1, `sys.stderr = None`, QGIS error window simulated) and checks that the plugin runs the full workflow without any error, and that it explains the fix when OpenCV is missing. |

Run:

```
QT_QPA_PLATFORM=offscreen /usr/bin/python3.12 tests/qgis_integration_test.py
```

`numpy2_mismatch_test.py` needs numpy 2 and OpenCV 4.10 wheels for the QGIS Python in a folder `np2env/` at the
repository root (ignored by git):

```
python3 -m pip install --target np2env --python-version 3.12 --only-binary=:all: \
    --platform manylinux2014_x86_64 --no-deps "numpy==2.2.6" "opencv-python-headless==4.10.0.84"
QT_QPA_PLATFORM=offscreen /usr/bin/python3.12 tests/numpy2_mismatch_test.py
```

Each test prints `PASS` / `FAIL` per check and `FAILURES: 0` at the end when everything passes.
