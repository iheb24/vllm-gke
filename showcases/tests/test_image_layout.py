import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

METHODS = {
    "tag": {"env": {"TAG_FAKE_MODEL": "1"}, "payload": {"question": "How many incident notes are there?"}},
    "cag": {"env": {"CAG_FAKE_MODEL": "1", "CAG_TOKENIZER": "estimated"}, "payload": {"question": "What is the idle monthly cost of the stack?"}},
    "mag": {"env": {"MAG_FAKE_MODEL": "1"}, "payload": {"user_id": "layout", "session_id": "s1", "question": "remember: layout check"}},
}

BOOT_SNIPPET = """
import json
import sys

sys.path.insert(0, sys.argv[1])
import app
from fastapi.testclient import TestClient

payload = json.loads(sys.argv[2])
with TestClient(app.app) as client:
    health = client.get("/healthz")
    assert health.status_code == 200, health.text
    resp = client.post("/chat", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method"]
    assert body["answer"]
print("BOOT OK")
"""


def replicate_copy_set(dockerfile, src_root, dest_root):
    copied = []
    for line in dockerfile.read_text().splitlines():
        line = line.strip()
        if not line.startswith("COPY "):
            continue
        parts = line[len("COPY "):].split()
        sources, dest = parts[:-1], parts[-1]
        for source in sources:
            src = src_root / source
            if source.endswith("/"):
                target = dest_root / dest.rstrip("/")
                shutil.copytree(src, target, dirs_exist_ok=True)
                copied += [str(p.relative_to(dest_root)) for p in sorted(target.rglob("*")) if p.is_file()]
            else:
                target_dir = dest_root if dest in (".", "./") else dest_root / dest.rstrip("/")
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target_dir / src.name)
                copied.append(str((target_dir / src.name).relative_to(dest_root)))
    return copied


@pytest.mark.parametrize("method", ["tag", "cag", "mag"])
def test_image_layout_boots(method, tmp_path):
    src_dir = REPO_ROOT / "showcases" / method
    layout = tmp_path / "app"
    layout.mkdir()
    copied = replicate_copy_set(src_dir / "Dockerfile", src_dir, layout)
    assert copied, "no COPY instructions parsed"
    assert "app.py" in copied
    assert "requirements.txt" in copied

    volume = tmp_path / "vol"
    volume.mkdir()
    env = dict(os.environ)
    env.update(METHODS[method]["env"])
    env["TAG_DB_PATH"] = str(volume / "serving.db")
    env["MAG_DB_PATH"] = str(volume / "mag.db")

    result = subprocess.run(
        [sys.executable, "-c", BOOT_SNIPPET, str(layout), json.dumps(METHODS[method]["payload"])],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, f"{method} layout failed to boot:\n{result.stdout}\n{result.stderr}"
    assert "BOOT OK" in result.stdout
