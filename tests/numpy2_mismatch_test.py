# Auto Georeference - automated test. Authors: Radu Andrei & Claude - MIT License
"""Reproduce the Windows situation: numpy 2 installed over a QGIS whose GDAL was built for
numpy 1, and sys.stderr = None. Then run the whole plugin flow."""
import os, sys, math, tempfile
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'np2env'))                  # numpy 2 + opencv 4.10 first
sys.path.insert(1, os.path.join(HERE, '..', 'qgis_auto_georeference'))
import subprocess
NP2 = os.path.join(HERE, '..', 'np2env')
# the user's crash: numpy 2 over QGIS's GDAL, no stderr, anything calling gdal.UseExceptions()
repro = subprocess.run([sys.executable, '-c', f'''
import sys; sys.path.insert(0, {NP2!r}); sys.stderr = None
seen = []
sys.excepthook = lambda t, v, tb: seen.append(f"{{t.__name__}}: {{v}}")   # like QGIS's error window
from osgeo import gdal
ds = gdal.GetDriverByName("MEM").Create("", 10, 10, 1)
try:
    ds.GetRasterBand(1).ReadAsArray()
except Exception:
    pass
print("QGIS ERROR WINDOW WOULD SHOW:", seen)
'''], capture_output=True, text=True)
_REPRO = repro.stdout.strip()
sys.stderr = None          # from here on: like QGIS on Windows
ERROR_WINDOW = []
sys.excepthook = lambda t, v, tb: ERROR_WINDOW.append(f'{t.__name__}: {v}')

from qgis.core import QgsApplication, QgsRasterLayer, QgsProject, QgsCoordinateReferenceSystem, QgsRectangle
qgs = QgsApplication([], True); qgs.setPrefixPath('/usr', True); qgs.initQgis()
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
import numpy as np
from osgeo import gdal, osr
out = sys.stdout
def say(*a): out.write(' '.join(str(x) for x in a) + '\n'); out.flush()
fails = 0
def check(name, cond, extra=''):
    global fails
    say(('PASS ' if cond else 'FAIL ') + name + (f'   [{extra}]' if extra else ''))
    fails += (not cond)

say('numpy', np.__version__, np.__file__)
tmp = tempfile.mkdtemp()
rng = np.random.default_rng(0)

# basemap written with raw bytes (no gdal_array)
BW, BH, RES, X0, Y0 = 3000, 2000, 1.0, 585000.0, 327000.0
import cv2
g = np.zeros((BH, BW), np.float32)
for s in (4, 16, 64):
    g += cv2.resize(rng.random((BH // s + 2, BW // s + 2)).astype(np.float32), (BW, BH), interpolation=cv2.INTER_CUBIC)
g = cv2.normalize(g, None, 0, 200, cv2.NORM_MINMAX).astype(np.uint8)
for _ in range(1500):
    x, y = int(rng.integers(0, BW)), int(rng.integers(0, BH))
    cv2.rectangle(g, (x, y), (x + int(rng.integers(6, 40)), y + int(rng.integers(6, 40))), int(rng.integers(60, 255)), -1)
base_path = os.path.join(tmp, 'base.tif')
ds = gdal.GetDriverByName('GTiff').Create(base_path, BW, BH, 3, gdal.GDT_Byte)
for i in range(3): ds.GetRasterBand(i + 1).WriteRaster(0, 0, BW, BH, g.tobytes())
ds.SetGeoTransform((X0, RES, 0, Y0, 0, -RES)); sr = osr.SpatialReference(); sr.ImportFromEPSG(3844); ds.SetProjection(sr.ExportToWkt()); ds = None
Gb = np.array([[RES, 0, X0], [0, -RES, Y0], [0, 0, 1]])
PW, PH, PRES, TH = 2400, 1800, 0.6, math.radians(-8)
c, s = math.cos(TH), math.sin(TH)
P = np.array([[PRES * c, PRES * s, 0], [PRES * s, -PRES * c, 0], [0, 0, 1]])
P[:2, 2] = np.array([586500.0, 326000.0]) - P[:2, :2] @ np.array([PW / 2, PH / 2])
M = np.linalg.inv(Gb) @ P
photo = cv2.warpAffine(g, M[:2], (PW, PH), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP)
photo_path = os.path.join(tmp, 'photo.jpg'); cv2.imwrite(photo_path, photo)

check("user's error reproduced with the old way of reading pixels",
      "AttributeError" in _REPRO, _REPRO)
saved = None
# ---- the plugin, same conditions (stderr None, numpy 2) ----
import auto_georeference as ag
check('plugin imports without dependency error', ag._DEPENDENCY_ERROR is None, ag._DEPENDENCY_ERROR or '')
layer = QgsRasterLayer(base_path, 'base'); QgsProject.instance().addMapLayer(layer)
canvas = QgsMapCanvas(); canvas.resize(1200, 800); canvas.show(); qgs.processEvents()
canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3844')); canvas.setLayers([layer])
canvas.setExtent(QgsRectangle(585600, 325300, 587400, 326700)); qgs.processEvents()
class Iface:
    def mapCanvas(self): return canvas
    def mainWindow(self): return None
plugin = ag.AutoGeoreferencePlugin(Iface())
out_path = os.path.join(tmp, 'result.tif')
msgs = []
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (photo_path, ''))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out_path, ''))
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(a[2]))
QMessageBox.critical = staticmethod(lambda *a, **k: msgs.append('CRITICAL ' + a[2]))
state = {}
def fake_exec(self):
    self.resize(1500, 950); self.show(); qgs.processEvents()
    rds = gdal.Open(self.ref_path); gt = rds.GetGeoTransform(); rds = None
    Gr = np.array([[gt[1], 0, gt[0]], [0, gt[5], gt[3]], [0, 0, 1]])
    S = lambda t: np.array([[1, 0, t], [0, 1, t], [0, 0, 1.0]])
    A_true = np.linalg.inv(Gr) @ Gb @ S(0.5) @ M @ S(-0.5)
    rough = np.array([[1.04, -0.03, 30], [0.03, 1.04, -20], [0, 0, 1]]) @ A_true
    self.set_transformation(rough[:2]); self.on_auto_refine()
    pts = np.array([[0, 0, 1], [PW, 0, 1], [PW, PH, 1], [0, PH, 1]], float).T
    state['err'] = np.max(np.linalg.norm((np.vstack([self.get_transformation(), [0, 0, 1]]) @ pts - A_true @ pts)[:2], axis=0))
    state['refined'] = self.refined; state['status'] = self.status_label.text()
    return QDialog.Accepted
ag.AlignmentDialog.exec = fake_exec
plugin.run()
check('whole flow runs with numpy 2 + no stderr', os.path.exists(out_path) and not any(m.startswith('CRITICAL') for m in msgs),
      ' | '.join(m.replace('\n', ' ')[:200] for m in msgs))
check('no error window at any point in the new plugin', not ERROR_WINDOW, str(ERROR_WINDOW)[:200])
check('auto-refine accurate', state.get('refined') and state.get('err', 99) < 1.0,
      f"err {state.get('err', -1):.2f} ref px | {state.get('status', '')[:70]}")

# ---- missing OpenCV: plugin must still load and explain the fix ----
code = f"""
import sys, os; os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0, {os.path.join(HERE, '..', 'qgis_auto_georeference')!r})
sys.modules['cv2'] = None      # simulate: OpenCV not installed
sys.stderr = None
from qgis.core import QgsApplication; q = QgsApplication([], False); q.initQgis()
import auto_georeference as ag
from qgis.PyQt.QtWidgets import QMessageBox
shown = []
QMessageBox.critical = staticmethod(lambda *a, **k: shown.append(a[2]))
ag.AutoGeoreferencePlugin(None).run()
print('SHOWN' if shown and 'repair_dependencies.bat' in shown[0] else 'NOT SHOWN', repr(ag._DEPENDENCY_ERROR[:60]))
"""
r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
check('without OpenCV: plugin loads and shows the repair instructions', 'SHOWN' in r.stdout, (r.stdout + r.stderr[-300:]).strip()[:200])

say('\nFAILURES:', fails)
qgs.exitQgis()
