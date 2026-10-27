import os
import sys
import tempfile
from pathlib import Path

TAG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TAG_DIR))

os.environ.setdefault("TAG_FAKE_MODEL", "1")
_TEST_DB_DIR = tempfile.mkdtemp(prefix="tag-test-db-")
os.environ.setdefault("TAG_DB_PATH", str(Path(_TEST_DB_DIR) / "serving.db"))
