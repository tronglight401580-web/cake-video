"""Shared configuration for paths, environment options and processing defaults."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / 'models'
LUT_DIR = ROOT / 'luts'
STYLE_DIR = ROOT / 'styles'
PRESETS_FILE = Path(os.environ.get('APPDATA', Path.home())) / 'cake' / 'presets.json'
CAKE_SEG = os.environ.get('CAKE_SEG', 'auto')
CAKE_ANALYZER = os.environ.get('CAKE_ANALYZER', 'process')
CAKE_YUV = os.environ.get('CAKE_YUV') == '1'
ANALYSIS_SHORT = 360
SEG_EVERY = 2
PROCESS_WORKERS = 3
THREAD_WORKERS = 4
PREVIEW_SHORT = 720
LOOKAHEAD = 6
