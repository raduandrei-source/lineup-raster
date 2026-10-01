"""
Auto Georeference - QGIS plugin
Authors: Radu Andrei & Claude
License: MIT (see LICENSE)
https://github.com/raduandrei-source/qgis-auto-georeference
"""


def classFactory(iface):
    """Factory for the plugin"""
    from .auto_georeference import AutoGeoreferencePlugin
    return AutoGeoreferencePlugin(iface)
