# PyInstaller hook for rapidocr_onnxruntime
# Ensures all sub-modules and data files are collected.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all .onnx model files, config.yaml, etc.
datas = collect_data_files('rapidocr_onnxruntime')

# Collect ALL sub-modules so importlib.import_module() can resolve them
# (rapidocr_onnxruntime uses bare module names like 'ch_ppocr_v3_det')
hiddenimports = collect_submodules('rapidocr_onnxruntime')
