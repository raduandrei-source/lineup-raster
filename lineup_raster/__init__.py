"""
LineUp Raster - QGIS plugin
Authors: Radu Andrei & Claude
License: MIT (see LICENSE)
https://github.com/raduandrei-source/lineup-raster
"""


def classFactory(iface):
    """Factory for the plugin"""
    from .lineup_raster import LineUpRasterPlugin
    return LineUpRasterPlugin(iface)
