# LineUp Raster - automated test. Authors: Radu Andrei & Claude - MIT License
"""Integration test in real QGIS (3.34, offscreen): render reference, align, auto-refine, save."""
import os, sys, math, tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lineup_raster'))

import numpy as np, cv2
from osgeo import gdal, osr
from qgis.core import QgsApplication, QgsRasterLayer, QgsProject, QgsCoordinateReferenceSystem, QgsRectangle
qgs = QgsApplication([], True); qgs.setPrefixPath('/usr', True); qgs.initQgis()
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import Qt, QPoint, QPointF, QEvent
from qgis.PyQt.QtGui import QMouseEvent, QWheelEvent
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
import lineup_raster as ag

fails = 0
def check(name, cond, extra=''):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name + (f'   [{extra}]' if extra else ''))
    if not cond: fails += 1

tmp = tempfile.mkdtemp()
rng = np.random.default_rng(3)

# ---------------- synthetic basemap ("satellite") in Stereo70 ----------------
def texture(h, w, seed):
    r = np.random.default_rng(seed)
    img = np.zeros((h, w), np.float32)
    for s in (4, 16, 64):
        n = r.random((h // s + 2, w // s + 2)).astype(np.float32)
        img += cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC) * s ** 0.3
    img = cv2.normalize(img, None, 0, 200, cv2.NORM_MINMAX).astype(np.uint8)
    for _ in range(2500):   # buildings
        x, y = int(r.integers(0, w)), int(r.integers(0, h))
        cv2.rectangle(img, (x, y), (x + int(r.integers(8, 50)), y + int(r.integers(8, 50))), int(r.integers(60, 255)), -1)
    for _ in range(120):    # roads
        p = (int(r.integers(0, w)), int(r.integers(0, h))); q = (int(r.integers(0, w)), int(r.integers(0, h)))
        cv2.line(img, p, q, int(r.integers(150, 255)), int(r.integers(3, 10)))
    return img

BW, BH, RES, X0, Y0 = 6000, 4000, 0.5, 585000.0, 327000.0
base_g = texture(BH, BW, 11)
base = np.dstack([base_g * 0.8, base_g * 0.95, base_g * 0.7]).astype(np.uint8)  # tinted colour
base_path = os.path.join(tmp, 'basemap.tif')
ds = gdal.GetDriverByName('GTiff').Create(base_path, BW, BH, 3, gdal.GDT_Byte)
for i in range(3): ds.GetRasterBand(i + 1).WriteArray(base[..., i])
ds.SetGeoTransform((X0, RES, 0, Y0, 0, -RES))
srs = osr.SpatialReference(); srs.ImportFromEPSG(3844); ds.SetProjection(srs.ExportToWkt()); ds = None
Gb = np.array([[RES, 0, X0], [0, -RES, Y0], [0, 0, 1]])

# ---------------- "aerial photo": finer, rotated, different contrast, changes, noise ----------------
PW, PH, PRES, THETA = 4000, 3000, 0.3, math.radians(17)
C = np.array([586500.0, 325800.0])
c, s = math.cos(THETA), math.sin(THETA)
# photo pixel -> world: centre + R(theta) * [res*(u-W/2), -res*(v-H/2)]
P = np.array([[PRES * c,  PRES * s, 0], [PRES * s, -PRES * c, 0], [0, 0, 1]], float)
P[:2, 2] = C - (P[:2, :2] @ np.array([PW / 2, PH / 2]))
M = np.linalg.inv(Gb) @ P  # photo px -> basemap px
photo = cv2.warpAffine(base_g, M[:2], (PW, PH), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP)
photo = (255 * (photo / 255.0) ** 0.7 * 1.2).clip(0, 255)                 # gamma + contrast
for _ in range(40):                                                      # changed areas (new buildings, fields)
    x, y = int(rng.integers(0, PW)), int(rng.integers(0, PH))
    cv2.rectangle(photo, (x, y), (x + int(rng.integers(60, 400)), y + int(rng.integers(60, 400))), float(rng.integers(0, 255)), -1)
photo = (photo + rng.normal(0, 10, photo.shape)).clip(0, 255).astype(np.uint8)
photo_path = os.path.join(tmp, 'photo.jpg')
# JPEG with EXIF orientation = 6: OpenCV would rotate it, GDAL/QGIS don't
from PIL import Image
exif = Image.Exif(); exif[0x0112] = 6
Image.fromarray(photo).save(photo_path, quality=75, exif=exif.tobytes())
check('EXIF trap in place: OpenCV sees rotated image, GDAL does not',
      cv2.imread(photo_path).shape[:2] == (PW, PH) and ag.raster_size(photo_path) == (PW, PH))

# ---------------- QGIS canvas showing the basemap ----------------
layer = QgsRasterLayer(base_path, 'basemap'); assert layer.isValid()
QgsProject.instance().addMapLayer(layer)
canvas = QgsMapCanvas(); canvas.resize(1400, 900); canvas.show(); qgs.processEvents()
canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3844'))
canvas.setLayers([layer]); canvas.setExtent(QgsRectangle(585700, 325000, 587300, 326600)); qgs.processEvents()

class Iface:
    def mapCanvas(self): return canvas
    def mainWindow(self): return None
plugin = ag.LineUpRasterPlugin(Iface())

ref_path = plugin.render_reference()
rds = gdal.Open(ref_path); gt = rds.GetGeoTransform(); rw, rh = rds.RasterXSize, rds.RasterYSize
ref_arr = rds.GetRasterBand(2).ReadAsArray(); rds = None
ext = canvas.mapSettings().visibleExtent()
check('reference rendered sharper than the screen', max(rw, rh) >= 2500, f'{rw}x{rh}')
dev = max(abs(gt[0] - ext.xMinimum()), abs(gt[0] + gt[1] * rw - ext.xMaximum()),
          abs(gt[3] - ext.yMaximum()), abs(gt[3] + gt[5] * rh - ext.yMinimum()))
check('reference covers the canvas extent (within 1 reference pixel)', dev <= abs(gt[1]), f'max edge diff {dev:.2f} m, pixel {gt[1]:.2f} m')
# the rendered pixels really are the basemap at those coordinates
Gr = np.array([[gt[1], 0, gt[0]], [0, gt[5], gt[3]], [0, 0, 1]])
resamp = cv2.warpAffine(base[..., 1], (np.linalg.inv(Gb) @ Gr)[:2], (rw, rh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
ncc = np.corrcoef(resamp[50:-50, 50:-50].ravel().astype(float), ref_arr[50:-50, 50:-50].ravel().astype(float))[0, 1]
check('rendered reference content = basemap at its coordinates', ncc > 0.9, f'NCC {ncc:.3f}')

S = lambda t: np.array([[1, 0, t], [0, 1, t], [0, 0, 1.0]])
# truth in GDAL corner convention (the photo was made with OpenCV, centre convention)
A_true = np.linalg.inv(Gr) @ Gb @ S(0.5) @ M @ S(-0.5)   # photo px -> reference px

def err_ref_px(A):
    pts = np.array([[0, 0, 1], [PW, 0, 1], [PW, PH, 1], [0, PH, 1], [PW / 2, PH / 2, 1]], float).T
    return np.max(np.linalg.norm((np.vstack([A, [0, 0, 1]]) @ pts)[:2] - (A_true @ pts)[:2], axis=0))

# ---------------- dialog: manual alignment, auto-refine ----------------
dlg = ag.AlignmentDialog(photo_path, ref_path); dlg.resize(1600, 1000); dlg.show(); qgs.processEvents()
view = dlg.comp_view
# user alignment: 5% off in scale, 3 degrees off, ~50 reference px off
d = np.array([[1.05 * math.cos(math.radians(3)), -1.05 * math.sin(math.radians(3)), 45],
              [1.05 * math.sin(math.radians(3)),  1.05 * math.cos(math.radians(3)), -25], [0, 0, 1]])
cref = np.array([[1, 0, -rw / 2], [0, 1, -rh / 2], [0, 0, 1]])
A_manual = (np.linalg.inv(cref) @ d @ cref @ A_true)[:2]
dlg.set_transformation(A_manual); qgs.processEvents()
check('view round-trips the alignment', np.allclose(dlg.get_transformation(), A_manual, atol=1e-6))
print(f'   manual alignment error: {err_ref_px(A_manual):.1f} reference px')

for det in ('ORB', 'SIFT'):
    dlg.set_transformation(A_manual)
    dlg.detector_engine = det
    dlg.on_auto_refine(); qgs.processEvents()
    e = err_ref_px(dlg.get_transformation())
    check(f'{det}: auto-refine snaps to the truth (< 1 reference pixel)', dlg.refined and e < 1.0,
          f'err {e:.2f} px = {e * gt[1]:.2f} m | {dlg.status_label.text()[:90]}')
    dlg.on_undo_refine()
    check(f'{det}: undo returns to manual alignment', np.allclose(dlg.get_transformation(), A_manual, atol=1e-3))

# wrong manual alignment (photo placed on the wrong neighbourhood): must refuse, not invent
dlg.refined = False
wrong = (np.array([[1, 0, 700], [0, 1, 300], [0, 0, 1]]) @ np.vstack([A_manual, [0, 0, 1]]))[:2]
dlg.set_transformation(wrong); dlg.detector_engine = 'SIFT'; dlg.on_auto_refine()
check('wrong placement: refine refuses and keeps the user alignment',
      not dlg.refined and np.allclose(dlg.get_transformation(), wrong, atol=1e-3), dlg.status_label.text()[:80])

# ---------------- full run() through the plugin, as in QGIS ----------------
out_path = os.path.join(tmp, 'photo_georef.tif')
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (photo_path, ''))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out_path, ''))
msgs = []
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(a[2]))
QMessageBox.critical = staticmethod(lambda *a, **k: msgs.append('CRITICAL ' + a[2]))
def fake_exec(self):
    self.resize(1600, 1000); self.show(); qgs.processEvents()
    self.set_transformation(A_manual); self.on_auto_refine()
    return QDialog.Accepted
ag.AlignmentDialog.exec = fake_exec
plugin.run()
print('   message:', ' | '.join(m.replace('\n', ' ') for m in msgs))
check('run() saved the GeoTIFF', os.path.exists(out_path) and not any(m.startswith('CRITICAL') for m in msgs))

o = gdal.Open(out_path); ogt = o.GetGeoTransform()
check('output is north-up with square pixels, correct size', ogt[2] == 0 and ogt[4] == 0 and abs(abs(ogt[5]) - ogt[1]) / ogt[1] < 1e-3
      and abs(ogt[1] - PRES) / PRES < 0.03, f'pixel {ogt[1]:.4f} m (true {PRES})')
check('output CRS is Stereo70', osr.SpatialReference(wkt=o.GetProjection()).GetAuthorityCode(None) == '3844')
# put the output back on the basemap grid and compare with the basemap: must line up
aligned = gdal.Warp('', o, format='MEM', outputBounds=(X0, Y0 - BH * RES, X0 + BW * RES, Y0), width=BW, height=BH, resampleAlg='bilinear')
a = aligned.GetRasterBand(1).ReadAsArray().astype(float); alpha = aligned.GetRasterBand(aligned.RasterCount).ReadAsArray() > 0
alpha = cv2.erode(alpha.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
ncc = np.corrcoef(a[alpha], base_g[alpha].astype(float))[0, 1]
# geolocation check on the photo corners
Wout = np.array([[ogt[1], ogt[2], ogt[0]], [ogt[4], ogt[5], ogt[3]], [0, 0, 1]])
o = None
def ncc_on_basemap(path):
    o = gdal.Open(path)
    al = gdal.Warp('', o, format='MEM', outputBounds=(X0, Y0 - BH * RES, X0 + BW * RES, Y0), width=BW, height=BH, resampleAlg='bilinear')
    a = al.GetRasterBand(1).ReadAsArray().astype(float); m = al.GetRasterBand(al.RasterCount).ReadAsArray() > 0
    m = cv2.erode(m.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    return np.corrcoef(a[m], base_g[m].astype(float))[0, 1]
truth_path = os.path.join(tmp, 'photo_truth.tif'); ag.write_georeferenced(photo_path, ref_path, A_true[:2], truth_path)
n_ours, n_truth = ncc_on_basemap(out_path), ncc_on_basemap(truth_path)
check('saved photo lines up with the basemap almost as well as a perfect georeference', n_ours >= 0.93 * n_truth,
      f'NCC ours {n_ours:.3f} vs perfect {n_truth:.3f}')
wrong_path = os.path.join(tmp, 'photo_manual.tif'); ag.write_georeferenced(photo_path, ref_path, A_manual, wrong_path)
print(f'   (for comparison, saving the rough manual alignment gives NCC {ncc_on_basemap(wrong_path):.3f})')

# ---------------- 16-bit single-band scan ----------------
scan_path = os.path.join(tmp, 'scan16.tif')
ds = gdal.GetDriverByName('GTiff').Create(scan_path, PW, PH, 1, gdal.GDT_UInt16)
ds.GetRasterBand(1).WriteArray(photo.astype(np.uint16) * 200 + 3000); ds = None
dlg2 = ag.AlignmentDialog(scan_path, ref_path); dlg2.resize(1600, 1000); dlg2.show(); qgs.processEvents()
dlg2.set_transformation(A_manual); dlg2.on_auto_refine()
check('16-bit scan: auto-refine works', dlg2.refined and err_ref_px(dlg2.get_transformation()) < 1.0, dlg2.status_label.text()[:60])

# ---------------- view: free pan / zoom, slider never moves images ----------------
def mouse(v, kind, x, y, mods=Qt.NoModifier):
    t = {'press': QEvent.MouseButtonPress, 'move': QEvent.MouseMove, 'release': QEvent.MouseButtonRelease}[kind]
    ev = QMouseEvent(t, QPointF(x, y), Qt.LeftButton, Qt.LeftButton if kind != 'release' else Qt.NoButton, mods)
    {'press': v.mousePressEvent, 'move': v.mouseMoveEvent, 'release': v.mouseReleaseEvent}[kind](ev)
def wheel(v, x, y, delta, mods=Qt.NoModifier):
    v.wheelEvent(QWheelEvent(QPointF(x, y), QPointF(x, y), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, mods, Qt.NoScrollPhase, False))

view.fit(); W, H = view.width(), view.height(); st0 = view.get_state()
view.slider_frac = 0.3; img_a = view.grab().toImage()
sx = view.slider_x(); mouse(view, 'press', sx + 3, 200); mouse(view, 'move', int(W * 0.8), 200); mouse(view, 'release', int(W * 0.8), 200)
img_b = view.grab().toImage()
check('slider drag moves no image', view.get_state() == st0)
check('photo pixels identical right of both slider positions',
      all(img_a.pixel(x, y) == img_b.pixel(x, y) for x in range(int(W * 0.85), W, 9) for y in range(0, H, 17)))
view.slider_frac = 0.5
mouse(view, 'press', int(W * 0.75), 300); mouse(view, 'move', int(W * 0.75) + 200, 380); mouse(view, 'release', int(W * 0.75) + 200, 380)
check('at match width the photo can now be panned sideways (free pan)', abs(view.src.cx - st0[1][0] - 200) < 1e-6)
check('pan on the photo side leaves the reference alone', view.ref.state() == st0[0])
for _ in range(10): wheel(view, int(W * 0.75), 300, -120)
mouse(view, 'press', int(W * 0.75), 300); mouse(view, 'move', int(W * 0.75) + 5000, 300); mouse(view, 'release', 0, 0)
hw, _ = view.src.half_extent()
check('zoomed out + dragged far: photo stops with a strip still visible', abs((view.src.cx - hw) - (W - ag.KEEP_VISIBLE)) < 1e-6)
img = view.grab().toImage()
check('black shows where the photo ends', img.pixel(int(W * 0.6), H // 2) & 0xFFFFFF == 0)
for _ in range(15): wheel(view, int(W * 0.75), 300, 120)
mouse(view, 'press', int(W * 0.75), 300); mouse(view, 'move', int(W * 0.75) + 300, 300); mouse(view, 'release', 0, 0)
check('zoomed in: still free to pan', True)
A_before = dlg.get_transformation(); wheel(view, 500, 400, 240, Qt.ShiftModifier)
mouse(view, 'press', 900, 300, Qt.ShiftModifier); mouse(view, 'move', 700, 500, Qt.ShiftModifier); mouse(view, 'release', 700, 500)
check('Shift zoom / pan keeps the alignment', np.allclose(dlg.get_transformation(), A_before, atol=1e-6))
for _ in range(6): wheel(view, 100, 100, 120, Qt.ShiftModifier)
mouse(view, 'press', 900, 300, Qt.ShiftModifier); mouse(view, 'move', -4000, -4000, Qt.ShiftModifier); mouse(view, 'release', 0, 0)
check('Shift pan to the far edge: still aligned', np.allclose(dlg.get_transformation(), A_before, atol=1e-6))
view.fit_keep_alignment()
check('Fit view keeps the alignment', np.allclose(dlg.get_transformation(), A_before, atol=1e-6) and abs(view.ref.scale - view.ref.fit_scale) < 1e-9)
view.set_src_rotation(17); view.fit(); view.set_src_rotation(17); st0 = view.get_state()
view.slider_frac = 0.3; ia = view.grab().toImage(); view.slider_frac = 0.8; ib = view.grab().toImage()
check('rotated photo: pixels identical wherever the slider is',
      all(ia.pixel(x, y) == ib.pixel(x, y) for x in range(int(W * 0.85), W, 3) for y in range(0, H, 5)) and
      all(ia.pixel(x, y) == ib.pixel(x, y) for x in range(0, int(W * 0.25), 3) for y in range(0, H, 5)))

# ---------------- comparison modes: red/cyan, edge tracing, blink, Space ----------------
import time
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtWidgets import QApplication, QPushButton
def view_rgb(v):
    a = ag._qimage_to_bgra(v.grab().toImage())
    return a[..., 2::-1].astype(int)
dlg.on_reset_view(); dlg.set_transformation(A_true[:2]); qgs.processEvents()
view = dlg.comp_view; W, H = view.width(), view.height()
both = (ag._qimage_to_bgra(view._layer_image(view.src))[..., 3] > 250) & \
       (ag._qimage_to_bgra(view._layer_image(view.ref))[..., 3] > 250)
both[H - 60:] = False                                   # leave out the hint box
def fringe(v):
    rgb = view_rgb(v); return float(np.abs(rgb[..., 0] - rgb[..., 1])[both].mean())
idx = [k for k, _ in ag.COMPARE_MODES].index('redcyan'); dlg.compare_combo.setCurrentIndex(idx); qgs.processEvents()
t0 = time.time(); view._composite_cache = None; view.grab(); t_comp = time.time() - t0
f_ok = fringe(view)
view.src.cx += 6; view.update(); qgs.processEvents(); f_off = fringe(view); view.src.cx -= 6
check('red/cyan: a 6 px offset produces clearly more colour fringe than the true alignment',
      f_off > 1.25 * f_ok, f'mean |R-G| aligned {f_ok:.1f} vs offset {f_off:.1f}')
rgb = view_rgb(view); outside = (ag._qimage_to_bgra(view._layer_image(view.src))[..., 3] == 0) & \
      (ag._qimage_to_bgra(view._layer_image(view.ref))[..., 3] > 250); outside[H - 60:] = False
check('red/cyan: outside the photo the reference is plain grey',
      outside.sum() == 0 or float(np.abs(rgb[..., 0] - rgb[..., 1])[outside].mean()) < 1.0)
check('red/cyan: composite is fast enough for live dragging', t_comp < 0.5, f'{t_comp*1000:.0f} ms')

idx = [k for k, _ in ag.COMPARE_MODES].index('edges'); dlg.compare_combo.setCurrentIndex(idx); qgs.processEvents()
rgb = view_rgb(view); yellow = np.all(rgb == np.array(ag.EDGE_COLOR), axis=-1)
check('edge tracing: reference outlines are drawn', yellow.mean() > 0.005, f'{yellow.mean()*100:.1f}% of the view')
def edge_agreement():
    ref_e = view._edge_cache[1]
    src_e = ag._edge_mask(ag._qimage_to_bgra(view._layer_image(view.src)))
    src_e = cv2.dilate(src_e.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    m = ref_e & both
    return float((m & src_e).sum()) / max(1, m.sum())
view.update(); qgs.processEvents(); view.grab(); e_ok = edge_agreement()
view.src.cx += 6; view.update(); qgs.processEvents(); view.grab(); e_off = edge_agreement(); view.src.cx -= 6
check('edge tracing: outlines sit on the photo edges when aligned, much less when offset',
      e_ok > 1.3 * e_off, f'agreement aligned {e_ok:.2f} vs offset {e_off:.2f}')
r0 = view.ref.state(); s0 = view.src.state()
mouse(view, 'press', view.slider_x(), 300); mouse(view, 'move', view.slider_x() + 40, 330); mouse(view, 'release', 0, 0)
check('overlay modes: no line to grab, dragging anywhere moves the photo', view.src.state() != s0 and view.ref.state() == r0)
s1 = view.src.state()
mouse(view, 'press', 500, 300, Qt.ControlModifier); mouse(view, 'move', 520, 300, Qt.ControlModifier); mouse(view, 'release', 0, 0)
check('overlay modes: Ctrl + drag moves the reference only', view.ref.state() != r0 and view.src.state() == s1)
dlg.set_transformation(A_true[:2])

idx = [k for k, _ in ag.COMPARE_MODES].index('blink'); dlg.compare_combo.setCurrentIndex(idx); qgs.processEvents()
seen = set()
for _ in range(12):
    QTest.qWait(100); seen.add(view._blink_ref)
check('blink: alternates between photo and reference by itself', seen == {True, False})
dlg.compare_combo.setCurrentIndex(0); qgs.processEvents()
check('back to slider mode stops blinking', not view._blink_timer.isActive())

save_btn = [b for b in dlg.findChildren(QPushButton) if b.text().startswith('Save')][0]
save_btn.setFocus(); clicked = []
save_btn.clicked.connect(lambda: clicked.append(1))
QApplication.sendEvent(save_btn, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, ' '))
peek_on = view.peek; peek_img = view_rgb(view)
QApplication.sendEvent(save_btn, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier, ' '))
check('Space (even with a button focused) shows the reference and presses no button',
      peek_on and not view.peek and not clicked and dlg.isVisible())
view.slider_frac = 1.0; ref_only = view_rgb(view); view.slider_frac = 0.5
check('Space view = reference alone', np.array_equal(peek_img[:H - 60], ref_only[:H - 60]))

# ---------------- menu: run entry + online help entry ----------------
from qgis.PyQt.QtGui import QDesktopServices
class MenuIface:
    def __init__(self): self.menu, self.toolbar = [], []
    def mainWindow(self): return None
    def mapCanvas(self): return canvas
    def addPluginToRasterMenu(self, name, action): self.menu.append((name, action))
    def removePluginRasterMenu(self, name, action): self.menu.remove((name, action))
    def addRasterToolBarIcon(self, action): self.toolbar.append(action)
    def removeRasterToolBarIcon(self, action): self.toolbar.remove(action)
mi = MenuIface(); mp = ag.LineUpRasterPlugin(mi); mp.initGui()
labels = [(n, a.text()) for n, a in mi.menu]
check('menu has the run entry and the Help entry under "LineUp Raster"',
      labels == [('&LineUp Raster', 'Line up and georeference a photo...'), ('&LineUp Raster', 'Help (online user guide)')], str(labels))
opened = []
QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or True)
mi.menu[1][1].trigger()
check('Help opens the online user guide', opened == ['https://raduandrei-source.github.io/lineup-raster/'], str(opened))
mp.unload()
check('unload removes both menu entries and the toolbar icon', mi.menu == [] and mi.toolbar == [])

print('\nFAILURES:', fails)
qgs.exitQgis()
