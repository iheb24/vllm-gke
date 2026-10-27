import os
import sys
from pathlib import Path

CAG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CAG_DIR))

os.environ.setdefault("CAG_FAKE_MODEL", "1")
