import os
import sys
import tempfile
from pathlib import Path

MAG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MAG_DIR))

os.environ.setdefault("MAG_FAKE_MODEL", "1")
_TEST_DB_DIR = tempfile.mkdtemp(prefix="mag-test-db-")
os.environ.setdefault("MAG_DB_PATH", str(Path(_TEST_DB_DIR) / "mag.db"))
