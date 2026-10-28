import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SH = REPO_ROOT / "showcases" / "demo.sh"

STUB = """#!/usr/bin/env bash
echo "$@" >> "$KUBECTL_STUB_LOG"
case "$*" in
  *"get deploy"*"ag-showcase"*)
    printf '%s' "$STUB_DEPLOYS"
    ;;
  "apply -f "*)
    dir="${@: -1}"
    if grep -q "YOUR_PROJECT_ID" "$dir"/*.yaml 2>/dev/null; then
      echo "APPLY_HAS_PLACEHOLDER" >> "$KUBECTL_STUB_LOG"
    fi
    grep -A1 "name: GATEWAY_MODEL" "$dir"/*.yaml 2>/dev/null \
      | grep "value:" | sed "s/.*value: //" >> "$KUBECTL_STUB_LOG"
    ;;
esac
exit 0
"""


@pytest.fixture()
def stub_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "kubectl"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "kubectl.log"

    def make_env(deploys=""):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "KUBECTL_STUB_LOG": str(log),
            "STUB_DEPLOYS": deploys,
        }
        return env

    return make_env, log


def run_demo(args, env, stdin_text=None):
    return subprocess.run(
        ["bash", str(DEMO_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        input=stdin_text,
        timeout=30,
    )


def stub_calls(log):
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["frobnicate", "tag"],
        ["up", "rag"],
        ["up"],
        ["up", "tag", "--bogus"],
        ["up", "tag", "--force", "extra"],
        ["status", "tag"],
        ["purge", "cag"],
        ["purge", "tag", "--yes"],
    ],
)
def test_usage_errors_exit_2(args, stub_env):
    make_env, _ = stub_env
    result = run_demo(args, make_env())
    assert result.returncode == 2
    assert "Usage: demo.sh" in result.stdout


def test_missing_kubectl_exits_3(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    result = run_demo(["status"], env)
    assert result.returncode == 3
    assert "kubectl not found" in result.stderr


def test_up_applies_when_nothing_active(stub_env):
    make_env, log = stub_env
    result = run_demo(["up", "tag"], make_env(""))
    assert result.returncode == 0, result.stderr + result.stdout
    calls = stub_calls(log)
    assert any("apply -f" in call for call in calls)
    assert "kubectl apply -f" in result.stdout
    assert "k8s/showcases/tag/" in result.stdout
    assert "cleanup:    demo.sh down tag" in result.stdout


def test_up_refused_when_another_showcase_active(stub_env):
    make_env, log = stub_env
    result = run_demo(["up", "tag"], make_env("ag-cag\n"))
    assert result.returncode == 1
    assert "already active" in result.stdout
    assert not any("apply" in call for call in stub_calls(log))


def test_up_force_overrides_active_showcase(stub_env):
    make_env, log = stub_env
    result = run_demo(["up", "tag", "--force"], make_env("ag-cag\n"))
    assert result.returncode == 0
    assert any("apply -f" in call for call in stub_calls(log))


def test_up_same_method_is_idempotent(stub_env):
    make_env, log = stub_env
    result = run_demo(["up", "cag"], make_env("ag-cag\n"))
    assert result.returncode == 0
    assert any("apply -f" in call for call in stub_calls(log))


def test_down_tag_deletes_manifests(stub_env):
    make_env, log = stub_env
    result = run_demo(["down", "tag"], make_env("ag-tag\n"))
    assert result.returncode == 0
    assert any("delete -f" in call and "tag/deployment.yaml" in call for call in stub_calls(log))


def test_down_mag_keeps_pvc(stub_env):
    make_env, log = stub_env
    result = run_demo(["down", "mag"], make_env("ag-mag\n"))
    assert result.returncode == 0
    assert "keeping PVC ag-mag-data" in result.stdout
    assert not any("delete pvc" in call for call in stub_calls(log))


def test_purge_mag_requires_confirmation_and_refuses_by_default(stub_env):
    make_env, log = stub_env
    result = run_demo(["purge", "mag"], make_env(""), stdin_text="n\n")
    assert result.returncode == 1
    assert "aborted" in result.stdout
    assert not any("delete pvc" in call for call in stub_calls(log))


def test_purge_mag_with_yes_flag(stub_env):
    make_env, log = stub_env
    result = run_demo(["purge", "mag", "--yes"], make_env(""))
    assert result.returncode == 0
    assert any("delete pvc ag-mag-data" in call for call in stub_calls(log))


def test_purge_mag_interactive_yes(stub_env):
    make_env, log = stub_env
    result = run_demo(["purge", "mag"], make_env(""), stdin_text="y\n")
    assert result.returncode == 0
    assert any("delete pvc ag-mag-data" in call for call in stub_calls(log))


@pytest.mark.parametrize("method,port", [("tag", 8091), ("cag", 8092), ("mag", 8093)])
def test_port_forward_mapping(stub_env, method, port):
    make_env, log = stub_env
    result = run_demo(["port-forward", method], make_env(""))
    assert result.returncode == 0
    assert any(
        f"port-forward -n rag svc/ag-{method} {port}:80" in call
        for call in stub_calls(log)
    )
    assert f"localhost:{port}" in result.stdout


def test_status_reports_active(stub_env):
    make_env, _ = stub_env
    result = run_demo(["status"], make_env("ag-cag\n"))
    assert result.returncode == 0
    assert "active showcase: cag" in result.stdout


def test_status_reports_none(stub_env):
    make_env, _ = stub_env
    result = run_demo(["status"], make_env(""))
    assert result.returncode == 0
    assert "no showcase active" in result.stdout


def test_up_substitutes_project_id_when_env_set(stub_env):
    make_env, log = stub_env
    env = make_env("")
    env["AG_PROJECT_ID"] = "my-proj"
    result = run_demo(["up", "tag"], env)
    assert result.returncode == 0
    assert not any("APPLY_HAS_PLACEHOLDER" in call for call in stub_calls(log))


def test_up_keeps_placeholder_without_env(stub_env):
    make_env, log = stub_env
    result = run_demo(["up", "tag"], make_env(""))
    assert result.returncode == 0
    assert any("APPLY_HAS_PLACEHOLDER" in call for call in stub_calls(log))


def test_up_gateway_model_override(stub_env):
    make_env, log = stub_env
    env = make_env("")
    env["AG_PROJECT_ID"] = "my-proj"
    env["AG_GATEWAY_MODEL"] = "qwen3-4b-cpu"
    result = run_demo(["up", "mag"], env)
    assert result.returncode == 0
    assert any("qwen3-4b-cpu" in call for call in stub_calls(log))
    assert not any("Qwen2.5-Coder-14B" in call for call in stub_calls(log))
