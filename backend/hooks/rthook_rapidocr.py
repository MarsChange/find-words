"""PyInstaller runtime hook for rapidocr_onnxruntime.

Fixes the path resolution that breaks in frozen (PyInstaller) bundles.

rapidocr_onnxruntime uses:
  1. Path(__file__).resolve().parent  → to find config.yaml and models/
  2. sys.path.append(root_dir)       → so importlib.import_module('ch_ppocr_v3_det') works
  3. importlib.import_module(name)   → with BARE module names (not dotted)

In a PyInstaller bundle, __file__ resolves to the temp extraction dir (sys._MEIPASS)
and collect_data_files places data under  _MEIPASS/rapidocr_onnxruntime/.
The bare importlib.import_module() calls need _MEIPASS/rapidocr_onnxruntime on sys.path.
"""

import sys
import os

if getattr(sys, 'frozen', False):
    _meipass = sys._MEIPASS
    _rapidocr_dir = os.path.join(_meipass, 'rapidocr_onnxruntime')

    # Ensure the rapidocr_onnxruntime package dir is on sys.path so
    # importlib.import_module('ch_ppocr_v3_det') resolves correctly.
    if os.path.isdir(_rapidocr_dir) and _rapidocr_dir not in sys.path:
        sys.path.insert(0, _rapidocr_dir)
