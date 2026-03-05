"""PyInstaller runtime hook for cv2 (OpenCV).

In PyInstaller bundles, cv2's bootstrap() function tries to:
  1. Pop cv2 from sys.modules
  2. Re-import cv2 via importlib.import_module("cv2")
This causes an import lock deadlock because FrozenImporter and numpy
imports conflict during the recursive import.

Fix: Pre-load the cv2 C extension directly from the .so file,
bypassing the bootstrap entirely.
"""
import sys
import os

if getattr(sys, 'frozen', False):
    _meipass = getattr(sys, '_MEIPASS', '')
    _cv2_dir = os.path.join(_meipass, 'cv2')

    # Find the cv2 C extension (.so / .pyd)
    _so_path = None
    if os.path.isdir(_cv2_dir):
        for _f in os.listdir(_cv2_dir):
            if _f.startswith('cv2') and (_f.endswith('.so') or _f.endswith('.pyd')):
                _so_path = os.path.join(_cv2_dir, _f)
                break

    if _so_path and os.path.exists(_so_path):
        import importlib.util as _iu
        _spec = _iu.spec_from_file_location('cv2', _so_path)
        if _spec:
            _mod = _iu.module_from_spec(_spec)
            sys.modules['cv2'] = _mod
            try:
                _spec.loader.exec_module(_mod)
            except Exception:
                # If direct loading fails, remove the partial module
                # and let the normal import try (may hang, but worth trying)
                sys.modules.pop('cv2', None)
