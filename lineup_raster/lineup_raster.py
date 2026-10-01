"""
LineUp Raster Plugin for QGIS

Authors: Radu Andrei & Claude
License: MIT (see LICENSE)
https://github.com/raduandrei-source/lineup-raster

Workflow:
  1. The current QGIS map view is rendered as the reference image (georeferenced).
  2. The user lines up the aerial photo over the reference by hand
     (masking-slider comparison: pan / zoom / rotate each image).
  3. Optional "Auto-refine": starting FROM the user's alignment, feature matching
     (SIFT or ORB) snaps the photo precisely. The result is shown in the same window,
     so the user sees it before saving and can undo it.
  4. What you see in the window is exactly what gets saved: the photo is written as a
     north-up GeoTIFF, with position, scale and rotation only (no shear / deformation).

Design rule for the comparison view:
  Each image has its OWN position on screen (centre, scale, rotation).
  The slider is only a clip mask: left of the line shows the reference,
  right of the line shows the photo. Moving the slider never moves an image.
"""

import io
import os
import sys
import math
import tempfile
import traceback
from pathlib import Path

# numpy / OpenCV are installed separately with pip, so they can be missing or mismatched.
# On Windows QGIS has no stderr (sys.stderr is None): numpy then crashes while trying to
# print its own error message, and the real reason is lost. So: import them with a
# temporary stderr, keep the real message, and show it with a fix instead of crashing.
_DEPENDENCY_ERROR = None
_saved_stderr = sys.stderr
_captured_stderr = io.StringIO()
sys.stderr = _captured_stderr
try:
    import numpy as np
    import cv2
    if not hasattr(cv2, 'SIFT_create'):
        raise ImportError(f'OpenCV {getattr(cv2, "__version__", "?")} is too old (4.4 or newer needed)')
except Exception as _e:
    np = cv2 = None
    _DEPENDENCY_ERROR = f'{type(_e).__name__}: {_e}\n{_captured_stderr.getvalue()}'.strip()
finally:
    sys.stderr = _saved_stderr

DEPENDENCY_HELP = (
    'The plugin needs OpenCV ("opencv-python-headless") in the QGIS Python, '
    'and it must match the numpy that came with QGIS.\n\n'
    'Fix (Windows): close QGIS, then double-click "repair_dependencies.bat" in the plugin '
    'folder and accept the administrator prompt. It restores the numpy that QGIS needs and '
    'installs a matching OpenCV. Then start QGIS again.')

from qgis.PyQt.QtCore import Qt, QPoint, QRect, QSize
from qgis.PyQt.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QTransform
from qgis.PyQt.QtWidgets import (QAction, QMessageBox, QFileDialog, QDialog,
                                 QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                                 QSlider, QComboBox, QWidget, QApplication)
from qgis.core import (QgsProject, QgsRasterLayer, QgsMapSettings,
                       QgsMapRendererParallelJob, QgsCoordinateReferenceSystem, QgsUnitTypes,
                       QgsMessageLog, Qgis)

try:
    from osgeo import gdal, gdalconst
except ImportError:
    gdal = None

# NOTE: do NOT call gdal.UseExceptions() here. It also imports GDAL's numpy module
# (gdal_array); if pip replaced the numpy that came with QGIS, that import fails inside
# C code and QGIS pops up its Python error window, even though Python can catch nothing.
# The plugin never needs gdal_array and checks every GDAL result explicitly instead.


def _gdal_open(path):
    ds = gdal.Open(path)
    if ds is None:
        raise ValueError(f'GDAL cannot open {path}')
    return ds


PREVIEW_MAX_DIM = 3000     # images in the comparison view are downsampled to this
MATCH_MAX_DIM = 3000       # working resolution of the reference for feature matching
REF_RENDER_MAX_DIM = 3000  # the reference is rendered up to this size (sharper than the screen)
KEEP_VISIBLE = 40          # px of each image that always stay on screen (so it can't get lost)


# ----------------------------------------------------------------------------------
# Raster helpers
# ----------------------------------------------------------------------------------

def _to_uint8(bands):
    """Stretch non-8-bit data (16-bit scans, float) to 0-255, same stretch for all bands."""
    if all(b.dtype == np.uint8 for b in bands):
        return bands
    stack = np.dstack(bands).astype(np.float32)
    lo, hi = np.percentile(stack, (1, 99))
    if hi <= lo:
        hi = lo + 1
    return [np.clip((b.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
            for b in bands]


def _read_band(band, bw, bh, alg):
    """Read one band as a numpy array WITHOUT GDAL's numpy module (gdal_array).

    gdal_array is compiled against one specific numpy version; if pip replaced the numpy
    that came with QGIS, it breaks. Reading raw bytes and wrapping them in numpy works
    with any numpy version.
    """
    if band.DataType == gdal.GDT_Byte:
        buf_type, dtype = gdal.GDT_Byte, np.uint8
    else:                                        # 16-bit, 32-bit, float -> float32
        buf_type, dtype = gdal.GDT_Float32, np.float32
    data = band.ReadRaster(0, 0, band.XSize, band.YSize, buf_xsize=bw, buf_ysize=bh,
                           buf_type=buf_type, resample_alg=alg)
    return np.frombuffer(data, dtype).reshape(bh, bw)


def raster_size(path):
    ds = _gdal_open(path)
    size = (ds.RasterXSize, ds.RasterYSize)
    ds = None
    return size


def read_raster(path, max_dim):
    """Read a raster with GDAL, downsampled so the longest side is <= max_dim.

    GDAL is used (not OpenCV) so the pixel grid is exactly the one GDAL/QGIS use when
    the georeference is written. OpenCV silently applies JPEG EXIF rotation, which
    would put every control point in the wrong place.

    Returns (BGR uint8 image, fx, fy) where fx, fy = read size / full size.
    """
    ds = _gdal_open(path)
    W, H = ds.RasterXSize, ds.RasterYSize
    f = min(1.0, max_dim / float(max(W, H)))
    bw, bh = max(1, int(round(W * f))), max(1, int(round(H * f)))
    alg = gdal.GRIORA_Average if f < 1.0 else gdal.GRIORA_NearestNeighbour

    band1 = ds.GetRasterBand(1)
    ct = band1.GetColorTable()
    if ds.RasterCount >= 3:
        bands = [_read_band(ds.GetRasterBand(i), bw, bh, alg) for i in (1, 2, 3)]
    elif ct is not None:
        idx = _read_band(band1, bw, bh, gdal.GRIORA_NearestNeighbour)
        lut = np.zeros((256, 3), np.uint8)
        for i in range(min(256, ct.GetCount())):
            lut[i] = ct.GetColorEntry(i)[:3]
        rgb = lut[np.clip(idx, 0, 255).astype(np.int64)]
        bands = [rgb[..., 0], rgb[..., 1], rgb[..., 2]]
    else:
        g = _read_band(band1, bw, bh, alg)
        bands = [g, g, g]
    ds = None
    r, g, b = _to_uint8(bands)
    return np.ascontiguousarray(np.dstack([b, g, r])), bw / float(W), bh / float(H)


def _h(m2x3):
    return np.vstack([np.asarray(m2x3, np.float64), [0.0, 0.0, 1.0]])


def _corner_to_cv(fx, fy):
    """Original-image pixel coordinates (GDAL / Qt convention: 0 = left EDGE of the first
    pixel) -> coordinates in an image downsampled by (fx, fy), in OpenCV convention
    (0 = CENTRE of the first pixel). Mixing the two conventions shifts everything by half
    a pixel, which on a coarse reference is easily half a metre."""
    return np.array([[fx, 0.0, -0.5], [0.0, fy, -0.5], [0.0, 0.0, 1.0]])


def _similarity_params(m):
    """scale, rotation (deg), of the linear part of a 2x3/3x3 matrix."""
    return math.hypot(m[0][0], m[1][0]), math.degrees(math.atan2(m[1][0], m[0][0]))


# ----------------------------------------------------------------------------------
# Automatic refinement (feature matching, starting from the manual alignment)
# ----------------------------------------------------------------------------------

def _detect_and_match(warped, valid, ref, radius, detector_engine):
    """Guided matching: a photo feature may only match reference features within
    `radius` px of where the current alignment puts it."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    warped = clahe.apply(warped)
    ref = clahe.apply(ref)
    ref_mask = cv2.dilate(valid, np.ones((3, 3), np.uint8), iterations=max(1, int(radius)))
    valid = cv2.erode(valid, np.ones((9, 9), np.uint8))   # ignore the photo's own border edge

    if detector_engine == 'ORB':
        detector = cv2.ORB_create(nfeatures=8000)
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    else:
        detector = cv2.SIFT_create(nfeatures=8000)
        matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))

    kp_w, des_w = detector.detectAndCompute(warped, valid)
    kp_r, des_r = detector.detectAndCompute(ref, ref_mask)
    if des_w is None or des_r is None or len(kp_w) < 10 or len(kp_r) < 10:
        raise ValueError('too few features found in the images')

    if detector_engine != 'ORB':
        des_w, des_r = np.float32(des_w), np.float32(des_r)
    k = min(8, len(kp_r))
    pw_all = np.float32([kp.pt for kp in kp_w])
    pr_all = np.float32([kp.pt for kp in kp_r])
    ratio = 0.8
    pts_w, pts_r = [], []
    for cands in matcher.knnMatch(des_w, des_r, k=k):
        if not cands:
            continue
        p = pw_all[cands[0].queryIdx]
        near = [c for c in cands
                if np.hypot(*(pr_all[c.trainIdx] - p)) <= radius]
        if not near:
            continue
        if len(near) >= 2 and near[0].distance >= ratio * near[1].distance:
            continue          # ambiguous among nearby candidates
        pts_w.append(p)
        pts_r.append(pr_all[near[0].trainIdx])
    return np.float32(pts_w), np.float32(pts_r)


def refine_alignment(src_path, ref_path, manual_affine, detector_engine='SIFT'):
    """Refine the user's alignment with feature matching.

    manual_affine: 2x3, original photo pixel -> original reference pixel.
    Returns (new_affine 2x3, info dict). Raises ValueError with a readable reason
    when no reliable result is found - it never returns a wild guess.

    Model: similarity (move + rotate + uniform scale). The photo is never sheared.
    """
    ref_bgr, rfx, rfy = read_raster(ref_path, MATCH_MAX_DIM)
    ref_g = cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2GRAY)
    h_r, w_r = ref_g.shape
    Dr = _corner_to_cv(rfx, rfy)
    A = _h(manual_affine)

    # Read the photo at about the resolution it will have on the working reference
    W, H = raster_size(src_path)
    s_needed = math.sqrt(abs(np.linalg.det((Dr @ A)[:2, :2])))
    if s_needed <= 1e-9:
        raise ValueError('invalid alignment')
    src_bgr, sfx, sfy = read_raster(src_path, max(64, int(1.5 * s_needed * max(W, H))))
    src_g = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2GRAY)
    Ds_inv = np.linalg.inv(_corner_to_cv(sfx, sfy))

    T0 = Dr @ A @ Ds_inv            # working photo px -> working reference px (manual)
    diag = math.hypot(w_r, h_r)
    C = np.eye(3)                   # correction found so far (working reference frame)
    info = None

    for radius_frac, thresh in ((0.06, 4.0), (0.015, 2.0)):
        T = C @ T0
        warped = cv2.warpAffine(src_g, T[:2], (w_r, h_r), flags=cv2.INTER_LINEAR, borderValue=0)
        valid = cv2.warpAffine(np.full(src_g.shape, 255, np.uint8), T[:2], (w_r, h_r),
                               flags=cv2.INTER_NEAREST, borderValue=0)
        if cv2.countNonZero(valid) < 0.02 * w_r * h_r:
            raise ValueError('the photo barely overlaps the reference')

        try:
            pw, pr = _detect_and_match(warped, valid, ref_g, radius_frac * diag, detector_engine)
            if len(pw) < 10:
                raise ValueError(f'only {len(pw)} candidate matches')
            M, inl = cv2.estimateAffinePartial2D(pw, pr, method=cv2.RANSAC,
                                                 ransacReprojThreshold=thresh,
                                                 maxIters=5000, confidence=0.999)
            if M is None:
                raise ValueError('no consistent transformation')
            inl = inl.ravel().astype(bool)
            n = int(inl.sum())
            if n < 12:
                raise ValueError(f'only {n} reliable matching points')
            # the matching points must be spread over the photo, not in one corner
            spread = np.ptp(pw[inl], axis=0)
            ys, xs = np.nonzero(valid)
            if spread[0] < 0.2 * np.ptp(xs) and spread[1] < 0.2 * np.ptp(ys):
                raise ValueError('matching points are all in one small area')
        except ValueError:
            if info is None:
                raise
            break                   # second (fine) pass failed: keep the first result

        C_new = _h(M) @ C
        # Sanity: the result must stay close to what the user aligned
        s, rot = _similarity_params(C_new)
        c = np.array([src_g.shape[1] / 2.0, src_g.shape[0] / 2.0, 1.0])
        shift = np.linalg.norm((C_new @ T0 @ c)[:2] - (T0 @ c)[:2])
        if not (0.8 < s < 1.25) or abs(rot) > 10 or shift > 0.15 * diag:
            if info is None:
                raise ValueError('the automatic result is too different from your alignment '
                                 '(probably a wrong match)')
            break
        C = C_new
        res = (np.hstack([pw[inl], np.ones((n, 1), np.float32)]) @ _h(M)[:2].T) - pr[inl]
        rms = float(np.sqrt(np.mean(np.sum(res ** 2, axis=1)))) / ((rfx + rfy) / 2.0)
        info = dict(points=n, rms=rms, scale_change=(s - 1) * 100, rotation_change=rot,
                    shift=shift / ((rfx + rfy) / 2.0))

    new_affine = np.linalg.inv(Dr) @ C @ Dr @ A
    return new_affine[:2], info


# ----------------------------------------------------------------------------------
# Writing the result
# ----------------------------------------------------------------------------------

def write_georeferenced(src_path, ref_path, affine, out_path):
    """Write the photo as a north-up GeoTIFF, placed by `affine`
    (original photo pixel -> original reference pixel). Returns pixel size in map units."""
    ref_ds = _gdal_open(ref_path)
    gt = ref_ds.GetGeoTransform()
    wkt = ref_ds.GetProjection()
    ref_ds = None
    G = np.array([[gt[1], gt[2], gt[0]], [gt[4], gt[5], gt[3]], [0.0, 0.0, 1.0]])
    Wm = G @ _h(affine)             # photo pixel -> map coordinates

    src_ds = _gdal_open(src_path)
    w, h = src_ds.RasterXSize, src_ds.RasterYSize
    gcps = []
    for px, py in ((0, 0), (w, 0), (w, h), (0, h), (w / 2.0, h / 2.0)):
        X, Y, _ = Wm @ np.array([px, py, 1.0])
        gcps.append(gdal.GCP(float(X), float(Y), 0.0, float(px), float(py)))

    last = src_ds.GetRasterBand(src_ds.RasterCount)
    has_alpha = last.GetColorInterpretation() == gdal.GCI_AlphaBand
    paletted = src_ds.GetRasterBand(1).GetColorTable() is not None

    tmp_vrt = '/vsimem/lineup_raster_tmp.vrt'
    vrt = gdal.Translate(tmp_vrt, src_ds, format='VRT', GCPs=gcps, outputSRS=wkt)
    out = gdal.Warp(out_path, vrt, format='GTiff', polynomialOrder=1,
                    dstAlpha=not has_alpha, resampleAlg='near' if paletted else 'bilinear',
                    creationOptions=['COMPRESS=DEFLATE', 'TILED=YES', 'BIGTIFF=IF_SAFER'],
                    multithread=True)
    if vrt is None or out is None:
        raise ValueError(f'GDAL could not write {out_path}: {gdal.GetLastErrorMsg()}')
    out = None
    vrt = None
    src_ds = None
    gdal.Unlink(tmp_vrt)
    return math.sqrt(abs(np.linalg.det(Wm[:2, :2])))


# ----------------------------------------------------------------------------------
# Comparison view
# ----------------------------------------------------------------------------------

def _event_pos(event):
    """Mouse/wheel position as QPoint, for both Qt5 and Qt6."""
    if hasattr(event, 'position'):
        return event.position().toPoint()
    return event.pos()


class _ImageLayer:
    """One image in the comparison view and where it sits on screen."""

    def __init__(self):
        self.pixmap = None
        self.cx = 0.0          # screen position of the image centre
        self.cy = 0.0
        self.scale = 1.0       # screen pixels per image pixel
        self.rotation = 0.0    # degrees, clockwise on screen
        self.fit_scale = 1.0   # scale at "match width"

    def transform(self):
        """Image pixel -> screen pixel."""
        t = QTransform()
        t.translate(self.cx, self.cy)
        t.rotate(self.rotation)
        t.scale(self.scale, self.scale)
        t.translate(-self.pixmap.width() / 2.0, -self.pixmap.height() / 2.0)
        return t

    def half_extent(self):
        """Half width / half height on screen of the (rotated) image's bounding box."""
        a = math.radians(self.rotation)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        w, h = self.pixmap.width(), self.pixmap.height()
        return (self.scale * (c * w + s * h) / 2.0,
                self.scale * (s * w + c * h) / 2.0)

    def state(self):
        return (self.cx, self.cy, self.scale, self.rotation)

    def set_state(self, st):
        self.cx, self.cy, self.scale, self.rotation = st


class ComparisonView(QWidget):
    """Reference and photo stacked on the same screen area, split by a masking slider.

    - Drag the black line: only changes which part of each image is visible.
    - Drag on the left of the line: moves the reference. On the right: moves the photo.
    - Scroll: zooms the image under the cursor, around the cursor.
    - Shift + drag / scroll: moves / zooms both together (alignment unchanged).
    - Pan and zoom are free at any zoom level; black shows where an image ends.
    """

    SLIDER_GRAB = 15    # px from the line: drag the line
    DEAD_ZONE = 20      # px from the line: below this (and above GRAB) nothing happens
    ZOOM_STEP = 1.15
    MIN_ZOOM = 0.02     # relative to "match width"
    MAX_ZOOM = 100.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ref = _ImageLayer()
        self.src = _ImageLayer()
        self.slider_frac = 0.5
        self.transparency = 0          # 0-100: photo drawn over the reference side
        self._user_moved = False
        self._mode = None              # 'slider' or 'pan'
        self._targets = []
        self._last_pos = QPoint()
        self.setMouseTracking(True)
        self.setMinimumSize(400, 300)
        self.setCursor(Qt.OpenHandCursor)

    # ---------- public API ----------

    def set_pixmaps(self, ref_pixmap=None, src_pixmap=None):
        """Replace image contents. Positions are kept unless the image size changed."""
        refit = False
        for layer, pix in ((self.ref, ref_pixmap), (self.src, src_pixmap)):
            if pix is None:
                continue
            if layer.pixmap is None or layer.pixmap.size() != pix.size():
                refit = True
            layer.pixmap = pix
        if refit:
            self.fit()
        self.update()

    def fit(self):
        """Match width: both images as wide as the view, centred, no distortion."""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        for layer in (self.ref, self.src):
            if layer.pixmap is None or layer.pixmap.width() == 0:
                continue
            layer.scale = layer.fit_scale = w / float(layer.pixmap.width())
            layer.cx, layer.cy = w / 2.0, h / 2.0
        self._user_moved = False
        self.update()

    def fit_keep_alignment(self):
        """Reference back to match width; the photo follows, so the alignment is kept."""
        if self.ref.pixmap is None or self.src.pixmap is None:
            return self.fit()
        m = self.src_to_ref_matrix()
        w, h = self.width(), self.height()
        self.ref.scale = self.ref.fit_scale = w / float(self.ref.pixmap.width())
        self.ref.cx, self.ref.cy = w / 2.0, h / 2.0
        self.set_src_to_ref_matrix(m)

    def set_src_rotation(self, degrees):
        """Rotate the photo around its own centre on screen."""
        self.src.rotation = float(degrees)
        self.update()

    def set_transparency(self, value):
        self.transparency = value
        self.update()

    def get_state(self):
        return self.ref.state(), self.src.state()

    def set_state(self, state):
        self.ref.set_state(state[0])
        self.src.set_state(state[1])
        self._user_moved = True
        self.update()

    def src_to_ref_matrix(self):
        """3x3 matrix: photo pixmap pixel -> reference pixmap pixel, as currently aligned."""
        ref_inv, _ = self.ref.transform().inverted()
        t = self.src.transform() * ref_inv   # photo -> screen -> reference
        return np.array([[t.m11(), t.m21(), t.dx()],
                         [t.m12(), t.m22(), t.dy()],
                         [0.0, 0.0, 1.0]], dtype=np.float64)

    def set_src_to_ref_matrix(self, m):
        """Place the photo so that photo pixmap pixel -> reference pixmap pixel equals m
        (a similarity). The reference stays where it is."""
        s, rot = _similarity_params(m)
        self.src.scale = self.ref.scale * s
        self.src.rotation = rot
        c = np.array([self.src.pixmap.width() / 2.0, self.src.pixmap.height() / 2.0, 1.0])
        q = m @ c
        p = self.ref.transform().map(float(q[0]), float(q[1]))
        self.src.cx, self.src.cy = p[0], p[1]
        self._user_moved = True
        self.update()

    def slider_x(self):
        return int(round(self.slider_frac * self.width()))

    # ---------- internals ----------

    def _keep_on_screen(self, layers):
        """Free pan / zoom at any zoom level, but keep a small strip on screen so an
        image can't get lost. Moved layers are corrected together by the same amount,
        so moving both (Shift) never changes their alignment."""
        if not layers:
            return
        boxes = [(l.cx - hw, l.cy - hh, l.cx + hw, l.cy + hh)
                 for l in layers for hw, hh in [l.half_extent()]]
        left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
        m = KEEP_VISIBLE
        dx = max(0.0, m - right) + min(0.0, (self.width() - m) - left)
        dy = max(0.0, m - bottom) + min(0.0, (self.height() - m) - top)
        for l in layers:
            l.cx += dx
            l.cy += dy

    def _layers_at(self, x, modifiers):
        if modifiers & Qt.ShiftModifier:
            layers = [self.ref, self.src]
        elif x < self.slider_x():
            layers = [self.ref]
        else:
            layers = [self.src]
        return [layer for layer in layers if layer.pixmap is not None]

    def _update_cursor(self, x):
        d = abs(x - self.slider_x())
        if d <= self.SLIDER_GRAB:
            self.setCursor(Qt.SizeHorCursor)
        elif d < self.DEAD_ZONE:
            self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)

    # ---------- Qt events ----------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._user_moved:
            self.fit()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = _event_pos(event)
        d = abs(pos.x() - self.slider_x())
        if d <= self.SLIDER_GRAB:
            self._mode = 'slider'
            self.setCursor(Qt.SizeHorCursor)
        elif d >= self.DEAD_ZONE:
            self._mode = 'pan'
            self._targets = self._layers_at(pos.x(), event.modifiers())
            self._last_pos = pos
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        pos = _event_pos(event)
        if self._mode == 'slider':
            self.slider_frac = min(1.0, max(0.0, pos.x() / float(max(1, self.width()))))
            self.update()
        elif self._mode == 'pan':
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            for layer in self._targets:
                layer.cx += dx
                layer.cy += dy
            self._keep_on_screen(self._targets)
            self._last_pos = pos
            self._user_moved = True
            self.update()
        else:
            self._update_cursor(pos.x())

    def mouseReleaseEvent(self, event):
        self._mode = None
        self._targets = []
        self._update_cursor(_event_pos(event).x())

    def wheelEvent(self, event):
        pos = _event_pos(event)
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        factor = self.ZOOM_STEP ** steps
        layers = self._layers_at(pos.x(), event.modifiers())
        # with Shift both images get the SAME factor, so the alignment is kept
        for layer in layers:
            factor = min(factor, layer.fit_scale * self.MAX_ZOOM / layer.scale)
            factor = max(factor, layer.fit_scale * self.MIN_ZOOM / layer.scale)
        for layer in layers:
            layer.cx = pos.x() + (layer.cx - pos.x()) * factor   # zoom around the cursor
            layer.cy = pos.y() + (layer.cy - pos.y()) * factor
            layer.scale *= factor
        self._keep_on_screen(layers)
        self._user_moved = True
        self.update()
        event.accept()

    def _layer_image(self, layer):
        """The layer drawn over the WHOLE view (transparent where the image ends).
        Cached: redrawn only when the image or its position changes, never because of
        the slider. The slider then only copies pieces of these images, so what is shown
        on each side is pixel-identical wherever the slider is."""
        key = (layer.pixmap.cacheKey(), layer.state(), self.width(), self.height())
        cached = getattr(layer, '_cache', None)
        if cached is not None and cached[0] == key:
            return cached[1]
        img = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setTransform(layer.transform())
        p.drawPixmap(0, 0, layer.pixmap)
        p.end()
        layer._cache = (key, img)
        return img

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        w, h = self.width(), self.height()
        sx = self.slider_x()
        left = QRect(0, 0, sx, h)
        right = QRect(sx, 0, w - sx, h)

        def draw(layer, part, opacity=1.0):
            if layer.pixmap is None or part.width() <= 0:
                return
            painter.setOpacity(opacity)
            painter.drawImage(part, self._layer_image(layer), part)   # plain copy, no scaling

        draw(self.ref, left)
        draw(self.src, right)
        if self.transparency > 0:
            draw(self.src, left, self.transparency / 100.0)
        painter.setOpacity(1.0)

        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawLine(sx, 0, sx, h)
        painter.end()


# ----------------------------------------------------------------------------------
# Dialog
# ----------------------------------------------------------------------------------

class AlignmentDialog(QDialog):
    """Manual alignment + optional automatic refinement. What you see is what gets saved."""

    def __init__(self, src_path, ref_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('LineUp Raster - line up the photo with the reference')
        self.setGeometry(50, 50, 1600, 1000)
        self.src_path = src_path
        self.ref_path = ref_path

        # Previews (read with GDAL); remember the factors to get back to full size
        self.src_preview, self.src_fx, self.src_fy = read_raster(src_path, PREVIEW_MAX_DIM)
        self.ref_preview, self.ref_fx, self.ref_fy = read_raster(ref_path, PREVIEW_MAX_DIM)

        self.detector_engine = 'SIFT'
        self.ref_sat = self.ref_bright = 100
        self.src_sat = self.src_bright = 100
        self._before_refine = None
        self.refined = False

        self.init_ui()
        self.update_ref_image()
        self.update_src_image()

    def init_ui(self):
        main_layout = QVBoxLayout()

        main_layout.addWidget(QLabel(
            'Left of the black line: reference (QGIS view).  Right: your photo.  '
            'Drag the black line to compare - the images never move with it.\n'
            'Drag on an image to move it, scroll to zoom it.  '
            'Shift + drag / scroll = move / zoom both together (keeps the alignment).\n'
            'Line up the photo with the reference, press "Auto-refine" and check the result, '
            'then "Save". What you see is what gets saved.'))

        rot_layout = QHBoxLayout()
        rot_layout.addWidget(QLabel('Rotate photo:'))
        self.rotate_slider = QSlider(Qt.Horizontal)
        self.rotate_slider.setRange(-1800, 1800)      # tenths of a degree
        self.rotate_slider.setValue(0)
        self.rotate_slider.setMinimumWidth(300)
        self.rotate_slider.valueChanged.connect(self.on_rotate_changed)
        rot_layout.addWidget(self.rotate_slider)
        self.rotate_label = QLabel('0.0°')
        self.rotate_label.setMinimumWidth(60)
        rot_layout.addWidget(self.rotate_label)
        btn_reset_rot = QPushButton('Reset rotation')
        btn_reset_rot.clicked.connect(lambda: self.rotate_slider.setValue(0))
        rot_layout.addWidget(btn_reset_rot)
        btn_fit = QPushButton('Fit view (keeps alignment)')
        btn_fit.clicked.connect(lambda: self.comp_view.fit_keep_alignment())
        rot_layout.addWidget(btn_fit)
        btn_reset_view = QPushButton('Start over (match width)')
        btn_reset_view.clicked.connect(self.on_reset_view)
        rot_layout.addWidget(btn_reset_view)
        rot_layout.addSpacing(20)
        rot_layout.addWidget(QLabel('Photo over reference:'))
        self.transparency_slider = QSlider(Qt.Horizontal)
        self.transparency_slider.setRange(0, 100)
        self.transparency_slider.setMaximumWidth(150)
        self.transparency_slider.valueChanged.connect(self.on_transparency_changed)
        rot_layout.addWidget(self.transparency_slider)
        self.trans_label = QLabel('0%')
        self.trans_label.setMinimumWidth(40)
        rot_layout.addWidget(self.trans_label)
        rot_layout.addStretch()
        main_layout.addLayout(rot_layout)

        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel('Reference  Sat:'))
        self.ref_sat_slider = self._make_slider(0, 200, 100, self.on_ref_color_changed)
        color_layout.addWidget(self.ref_sat_slider)
        color_layout.addWidget(QLabel('Bright:'))
        self.ref_bright_slider = self._make_slider(50, 150, 100, self.on_ref_color_changed)
        color_layout.addWidget(self.ref_bright_slider)
        color_layout.addSpacing(30)
        color_layout.addWidget(QLabel('Photo  Sat:'))
        self.src_sat_slider = self._make_slider(0, 200, 100, self.on_src_color_changed)
        color_layout.addWidget(self.src_sat_slider)
        color_layout.addWidget(QLabel('Bright:'))
        self.src_bright_slider = self._make_slider(50, 150, 100, self.on_src_color_changed)
        color_layout.addWidget(self.src_bright_slider)
        color_layout.addStretch()
        main_layout.addLayout(color_layout)

        self.comp_view = ComparisonView()
        main_layout.addWidget(self.comp_view, 1)

        refine_layout = QHBoxLayout()
        refine_layout.addWidget(QLabel('Feature detector:'))
        self.detector_combo = QComboBox()
        self.detector_combo.addItems(['SIFT (accurate, slower)', 'ORB (fast, less accurate)'])
        self.detector_combo.currentTextChanged.connect(self.on_detector_changed)
        refine_layout.addWidget(self.detector_combo)
        self.btn_refine = QPushButton('Auto-refine alignment')
        self.btn_refine.clicked.connect(self.on_auto_refine)
        refine_layout.addWidget(self.btn_refine)
        self.btn_undo = QPushButton('Undo auto-refine')
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self.on_undo_refine)
        refine_layout.addWidget(self.btn_undo)
        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        refine_layout.addWidget(self.status_label, 1)
        main_layout.addLayout(refine_layout)

        buttons = QHBoxLayout()
        btn_ok = QPushButton('Save georeferenced photo...')
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_ok)
        btn_cancel = QPushButton('Cancel')
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)
        main_layout.addLayout(buttons)

        self.setLayout(main_layout)

    @staticmethod
    def _make_slider(lo, hi, value, callback):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(value)
        s.setMaximumWidth(100)
        s.valueChanged.connect(callback)
        return s

    @staticmethod
    def cv_to_qpixmap(cv_img):
        """Convert OpenCV BGR / grayscale image to QPixmap (data is copied)."""
        if len(cv_img.shape) == 2:
            img = np.ascontiguousarray(cv_img)
            h, w = img.shape
            qi = QImage(img.data, w, h, w, QImage.Format_Grayscale8)
        else:
            img = np.ascontiguousarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))
            h, w, _ = img.shape
            qi = QImage(img.data, w, h, 3 * w, QImage.Format_RGB888)
        return QPixmap.fromImage(qi.copy())

    @staticmethod
    def adjust_colors(img, saturation, brightness):
        """Visual only - does not affect feature matching."""
        if saturation == 100 and brightness == 100:
            return img
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * saturation / 100.0, 0, 255)
        hsv[..., 2] = np.clip(hsv[..., 2] * brightness / 100.0, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    def update_ref_image(self):
        img = self.adjust_colors(self.ref_preview, self.ref_sat, self.ref_bright)
        self.comp_view.set_pixmaps(ref_pixmap=self.cv_to_qpixmap(img))

    def update_src_image(self):
        img = self.adjust_colors(self.src_preview, self.src_sat, self.src_bright)
        self.comp_view.set_pixmaps(src_pixmap=self.cv_to_qpixmap(img))

    # ---------- controls ----------

    def on_rotate_changed(self, value):
        self.rotate_label.setText(f'{value / 10.0:.1f}°')
        self.comp_view.set_src_rotation(value / 10.0)

    def _sync_rotation_slider(self):
        rot = self.comp_view.src.rotation
        self.rotate_slider.blockSignals(True)
        self.rotate_slider.setValue(int(round(rot * 10)))
        self.rotate_slider.blockSignals(False)
        self.rotate_label.setText(f'{rot:.2f}°')

    def on_reset_view(self):
        self.comp_view.fit()
        self.rotate_slider.setValue(0)
        self.comp_view.set_src_rotation(0.0)
        self._before_refine = None
        self.refined = False
        self.btn_undo.setEnabled(False)
        self.status_label.setText('')

    def on_detector_changed(self, text):
        self.detector_engine = 'ORB' if 'ORB' in text else 'SIFT'

    def on_transparency_changed(self, value):
        self.trans_label.setText(f'{value}%')
        self.comp_view.set_transparency(value)

    def on_ref_color_changed(self):
        self.ref_sat = self.ref_sat_slider.value()
        self.ref_bright = self.ref_bright_slider.value()
        self.update_ref_image()

    def on_src_color_changed(self):
        self.src_sat = self.src_sat_slider.value()
        self.src_bright = self.src_bright_slider.value()
        self.update_src_image()

    def on_auto_refine(self):
        before = self.comp_view.get_state()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.status_label.setText('Matching features...')
        QApplication.processEvents()
        try:
            new_affine, info = refine_alignment(self.src_path, self.ref_path,
                                                self.get_transformation(), self.detector_engine)
        except Exception as e:
            if not isinstance(e, ValueError):      # a real error, not "no reliable result"
                QgsMessageLog.logMessage(traceback.format_exc(), 'LineUp Raster', Qgis.Critical)
            self.status_label.setText(f'Auto-refine found no reliable result: {e}. '
                                      'Your alignment was kept.')
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._before_refine = before
        self.set_transformation(new_affine)
        self.refined = True
        self.btn_undo.setEnabled(True)
        self.status_label.setText(
            f'Refined with {info["points"]} matching points (error ~{info["rms"]:.1f} px of the '
            f'reference). Change vs. your alignment: moved {info["shift"]:.0f} px, '
            f'scale {info["scale_change"]:+.1f}%, rotation {info["rotation_change"]:+.2f}°. '
            'Check it with the slider; "Undo" returns to your alignment.')

    def on_undo_refine(self):
        if self._before_refine is not None:
            self.comp_view.set_state(self._before_refine)
            self._sync_rotation_slider()
            self._before_refine = None
            self.refined = False
            self.btn_undo.setEnabled(False)
            self.status_label.setText('Back to your alignment.')

    # ---------- alignment <-> full-resolution pixels ----------

    def get_transformation(self):
        """Current alignment as a 2x3 affine: original photo pixel -> original reference pixel."""
        m_preview = self.comp_view.src_to_ref_matrix()
        to_src_preview = np.diag([self.src_fx, self.src_fy, 1.0])
        from_ref_preview = np.diag([1.0 / self.ref_fx, 1.0 / self.ref_fy, 1.0])
        return (from_ref_preview @ m_preview @ to_src_preview)[:2]

    def set_transformation(self, affine):
        """Move the photo in the view to the given alignment (original pixel coordinates)."""
        m_preview = (np.diag([self.ref_fx, self.ref_fy, 1.0]) @ _h(affine) @
                     np.diag([1.0 / self.src_fx, 1.0 / self.src_fy, 1.0]))
        self.comp_view.set_src_to_ref_matrix(m_preview)
        self._sync_rotation_slider()


# ----------------------------------------------------------------------------------
# Plugin
# ----------------------------------------------------------------------------------

class LineUpRasterPlugin:
    """Main plugin class"""

    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()
        self.plugin_dir = str(Path(__file__).parent)

    def initGui(self):
        self.action = QAction('Line up and georeference a photo...', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToRasterMenu('&LineUp Raster', self.action)
        self.iface.addRasterToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginRasterMenu('&LineUp Raster', self.action)
        self.iface.removeRasterToolBarIcon(self.action)

    def run(self):
        if _DEPENDENCY_ERROR:
            QgsMessageLog.logMessage(_DEPENDENCY_ERROR, 'LineUp Raster', Qgis.Critical)
            QMessageBox.critical(None, 'LineUp Raster - missing / mismatched library',
                                 f'{DEPENDENCY_HELP}\n\nTechnical reason:\n{_DEPENDENCY_ERROR[:600]}')
            return
        try:
            if gdal is None:
                QMessageBox.critical(None, 'Error', 'GDAL not available')
                return

            source_path, _ = QFileDialog.getOpenFileName(
                None, 'Select aerial photo', '',
                'Raster files (*.tif *.TIF *.tiff *.img *.jp2 *.png *.jpg *.jpeg);;All files (*.*)')
            if not source_path:
                return

            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                ref_path = self.render_reference()
            finally:
                QApplication.restoreOverrideCursor()

            dialog = AlignmentDialog(source_path, ref_path)
            if dialog.exec() != QDialog.Accepted:
                return
            affine = dialog.get_transformation()

            output_path, _ = QFileDialog.getSaveFileName(
                None, 'Save georeferenced photo', '', 'GeoTIFF (*.tif);;All files (*.*)')
            if not output_path:
                return
            if not output_path.lower().endswith(('.tif', '.tiff')):
                output_path += '.tif'

            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                pixel_size = write_georeferenced(source_path, ref_path, affine, output_path)
            finally:
                QApplication.restoreOverrideCursor()

            crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            units = QgsUnitTypes.toString(crs.mapUnits())
            how = 'auto-refined' if dialog.refined else 'your manual alignment'
            QMessageBox.information(
                None, 'Saved',
                f'Saved to:\n{output_path}\n\nPlaced using {how}.\n'
                f'Photo pixel size: {pixel_size:.4g} {units}')

            self.project.addMapLayer(QgsRasterLayer(output_path, Path(output_path).stem))

        except Exception as e:
            QApplication.restoreOverrideCursor()
            # log the details (never print: on Windows QGIS stderr is None)
            QgsMessageLog.logMessage(traceback.format_exc(), 'LineUp Raster', Qgis.Critical)
            QMessageBox.critical(None, 'Error', f'Error:\n{str(e)}\n\n'
                                 'Details: View → Panels → Log Messages → "LineUp Raster".')

    def render_reference(self):
        """Render the current map view to a georeferenced GeoTIFF.

        Rendered by QGIS at up to REF_RENDER_MAX_DIM px (sharper than the screen, which
        helps feature matching). Pixel size is computed from the real image size.
        """
        canvas = self.iface.mapCanvas()
        base = canvas.mapSettings()
        if abs(base.rotation()) > 1e-9:
            raise ValueError('Please set the map rotation to 0° before georeferencing.')

        size = base.outputSize()
        k = max(1.0, min(3.0, REF_RENDER_MAX_DIM / float(max(size.width(), size.height()))))
        ms = QgsMapSettings(base)
        ms.setOutputSize(QSize(int(size.width() * k), int(size.height() * k)))
        if hasattr(ms, 'setDevicePixelRatio'):
            ms.setDevicePixelRatio(1.0)
        ms.setExtent(base.visibleExtent())

        job = QgsMapRendererParallelJob(ms)
        job.start()
        job.waitForFinished()
        image = job.renderedImage().convertToFormat(QImage.Format_RGB888)
        if image.isNull() or image.width() == 0:
            raise ValueError('Could not render the QGIS map view')

        w, h = image.width(), image.height()
        ptr = image.constBits()
        ptr.setsize(image.bytesPerLine() * h)
        rgb = np.frombuffer(ptr, np.uint8).reshape(h, image.bytesPerLine())[:, :w * 3]
        rgb = rgb.reshape(h, w, 3).copy()

        extent = ms.visibleExtent()
        tmp = tempfile.NamedTemporaryFile(suffix='_reference.tif', delete=False)
        tmp.close()
        ds = gdal.GetDriverByName('GTiff').Create(tmp.name, w, h, 3, gdal.GDT_Byte)
        if ds is None:
            raise ValueError(f'GDAL cannot create {tmp.name}')
        for i in range(3):
            ds.GetRasterBand(i + 1).WriteRaster(0, 0, w, h,
                                                np.ascontiguousarray(rgb[..., i]).tobytes())
        ds.SetGeoTransform((extent.xMinimum(), extent.width() / w, 0.0,
                            extent.yMaximum(), 0.0, -extent.height() / h))
        crs = ms.destinationCrs()
        if crs.isValid():
            ds.SetProjection(crs.toWkt())
        ds.FlushCache()
        ds = None
        return tmp.name
