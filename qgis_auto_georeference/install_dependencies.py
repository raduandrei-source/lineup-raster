#!/usr/bin/env python3
"""
Install (or repair) the Python libraries needed by the Auto Georeference QGIS plugin.

Authors: Radu Andrei & Claude - MIT License

Run it with the SAME Python that QGIS uses, with QGIS closed:
  Windows : double-click repair_dependencies.bat (finds QGIS, asks for admin rights, runs this)
  macOS   : /Applications/QGIS.app/Contents/MacOS/bin/python3 install_dependencies.py
            (the folder may differ between QGIS builds - use the python3 inside QGIS.app)
  Linux   : Debian/Ubuntu with QGIS from apt -> simply: sudo apt install python3-opencv
            other distributions -> python3 install_dependencies.py

What it does:
  1. Checks that this Python has GDAL (so it really is the QGIS Python).
  2. Checks that QGIS's GDAL can use the installed numpy. Only if it cannot (because numpy was
     replaced, e.g. by "pip install --upgrade numpy"), it installs a numpy that matches GDAL.
     A working numpy is never touched.
  3. Installs OpenCV (opencv-python-headless 4.10.0.84) with --no-deps, so pip cannot replace
     numpy again. Skipped when a working OpenCV with SIFT is already there.
  4. Checks everything the plugin needs and prints OK.

Options:  --force-opencv   reinstall OpenCV even if the current one works
"""

import subprocess
import sys

OPENCV = 'opencv-python-headless==4.10.0.84'   # works with numpy 1.x and 2.x
OPENCV_PACKAGES = ['opencv-python', 'opencv-contrib-python',
                   'opencv-python-headless', 'opencv-contrib-python-headless']


def check(code):
    """Run code in a fresh Python process (a broken import can't harm this one)."""
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def pip(*args):
    cmd = [sys.executable, '-m', 'pip', *args, '--disable-pip-version-check']
    print('  > pip ' + ' '.join(args))
    ok = subprocess.run(cmd).returncode == 0
    if not ok and args[0] == 'install':
        print('  ...retrying as a per-user install')
        ok = subprocess.run(cmd + ['--user']).returncode == 0
    return ok


def fail(msg):
    print('\nFAILED: ' + msg)
    print('If pip said "externally-managed-environment" (Debian/Ubuntu): sudo apt install python3-opencv')
    print('If it said "Access is denied" / "Permission denied": run it as administrator / with sudo.')
    sys.exit(1)


def main():
    print('Auto Georeference - dependency installer')
    print(f'Python: {sys.executable}  ({sys.version.split()[0]})\n')

    ok, out = check('from osgeo import gdal; print(gdal.__version__)')
    if not ok:
        fail('this Python has no GDAL, so it is not the Python that QGIS uses.\n'
             'Windows: use repair_dependencies.bat, or the "OSGeo4W Shell" of your QGIS.')
    print(f'[1/4] GDAL {out}')

    ok, np_version = check('import numpy; print(numpy.__version__)')
    if not ok:
        print('[2/4] numpy is missing - installing "numpy<2"')
        if not pip('install', 'numpy<2'):
            fail('could not install numpy')
        np_version = check('import numpy; print(numpy.__version__)')[1]
        numpy_changed = True
    else:
        numpy_changed = False

    ok, out = check('from osgeo import gdal_array')
    if ok:
        print(f'[2/4] numpy {np_version} works with QGIS\'s GDAL - left as it is')
    else:
        major = int(np_version.split('.')[0])
        target = 'numpy<2' if major >= 2 else 'numpy>=2,<2.3'
        print(f'[2/4] QGIS\'s GDAL cannot use numpy {np_version} (it was probably replaced).')
        print(f'      Installing {target} to match GDAL...')
        if not pip('install', target):
            fail('could not change numpy (is QGIS still open? administrator rights?)')
        ok, out = check('from osgeo import gdal_array')
        if not ok:
            fail('GDAL still cannot use numpy:\n' + out[-800:])
        np_version = check('import numpy; print(numpy.__version__)')[1]
        print(f'      numpy {np_version} now works with GDAL')
        numpy_changed = True

    ok, out = check('import cv2; cv2.SIFT_create(); print(cv2.__version__)')
    if ok and not numpy_changed and '--force-opencv' not in sys.argv:
        print(f'[3/4] OpenCV {out} already works - left as it is')
    else:
        print('[3/4] Installing OpenCV (' + OPENCV + ', without touching numpy)')
        installed = [p for p in OPENCV_PACKAGES
                     if check(f'import importlib.metadata as m; m.version("{p}")')[0]]
        if installed:
            pip('uninstall', '-y', *installed)
        if not pip('install', '--no-deps', OPENCV):
            fail('could not install OpenCV')

    ok, out = check('import numpy, cv2; from osgeo import gdal, gdal_array; cv2.SIFT_create(); '
                    'print("numpy", numpy.__version__, "| OpenCV", cv2.__version__, '
                    '"| GDAL", gdal.__version__)')
    if not ok:
        fail('final check failed:\n' + out[-800:])
    print(f'[4/4] OK  {out}')
    print('\nDone. Start QGIS and use  Raster > Auto Georeference > Auto Georeference Raster.')


if __name__ == '__main__':
    main()
