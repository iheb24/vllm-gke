import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIRS = {
    "tag": REPO_ROOT / "k8s" / "showcases" / "tag",
    "cag": REPO_ROOT / "k8s" / "showcases" / "cag",
    "mag": REPO_ROOT / "k8s" / "showcases" / "mag",
}
MANIFEST_FILES = [
    REPO_ROOT / "k8s" / "showcases" / "tag" / "deployment.yaml",
    REPO_ROOT / "k8s" / "showcases" / "cag" / "deployment.yaml",
    REPO_ROOT / "k8s" / "showcases" / "mag" / "deployment.yaml",
    REPO_ROOT / "k8s" / "showcases" / "mag" / "pvc.yaml",
]
EXPECTED_PORTS = {"tag": 8091, "cag": 8092, "mag": 8093}


def load_docs(path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def deployments(path):
    return [d for d in load_docs(path) if d.get("kind") == "Deployment"]


def services(path):
    return [d for d in load_docs(path) if d.get("kind") == "Service"]


def container_of(deployment):
    return deployment["spec"]["template"]["spec"]["containers"][0]


@pytest.mark.parametrize("method", ["tag", "cag", "mag"])
def test_deployment_basics(method):
    deploys = deployments(MANIFEST_DIRS[method] / "deployment.yaml")
    assert len(deploys) == 1
    deploy = deploys[0]
    assert deploy["metadata"]["name"] == f"ag-{method}"
    assert deploy["metadata"]["namespace"] == "rag"
    assert deploy["metadata"]["labels"]["ag-showcase"] == method
    spec = deploy["spec"]
    assert spec["replicas"] == 1
    template_labels = spec["template"]["metadata"]["labels"]
    assert template_labels["ag-showcase"] == method
    pod_spec = spec["template"]["spec"]
    assert pod_spec["nodeSelector"] == {"workload": "rag"}


@pytest.mark.parametrize("method", ["tag", "cag", "mag"])
def test_container_contract(method):
    container = container_of(deployments(MANIFEST_DIRS[method] / "deployment.yaml")[0])
    assert "YOUR_PROJECT_ID" in container["image"]
    port = EXPECTED_PORTS[method]
    assert container["ports"][0]["containerPort"] == port
    env = {item["name"]: item for item in container["env"]}
    assert env["GATEWAY_URL"]["value"].endswith("/v1")
    assert env["GATEWAY_API_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "vllm-api-key",
        "key": "api-key",
    }
    assert env["GATEWAY_MODEL"]["value"] == "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
    for item in container["env"]:
        assert "valueFrom" in item or isinstance(item["value"], str)
        assert "valueFrom" not in item or "secretKeyRef" in item["valueFrom"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    resources = container["resources"]
    assert resources["requests"] == {"cpu": "100m", "memory": "256Mi"}
    assert resources["limits"]["cpu"] == "500m"


def test_cag_memory_limit_is_higher():
    container = container_of(deployments(MANIFEST_DIRS["cag"] / "deployment.yaml")[0])
    assert container["resources"]["limits"]["memory"] == "768Mi"


@pytest.mark.parametrize("method", ["tag", "cag", "mag"])
def test_service_is_clusterip_only(method):
    svcs = services(MANIFEST_DIRS[method] / "deployment.yaml")
    assert len(svcs) == 1
    svc = svcs[0]
    assert svc["metadata"]["name"] == f"ag-{method}"
    assert svc["metadata"]["namespace"] == "rag"
    assert svc["spec"]["type"] == "ClusterIP"
    rendered = yaml.safe_dump(svc)
    assert "LoadBalancer" not in rendered
    assert "NodePort" not in rendered
    port = svc["spec"]["ports"][0]
    assert port["port"] == 80
    assert port["targetPort"] == EXPECTED_PORTS[method]


def test_tag_uses_emptydir_not_pvc():
    deploy = deployments(MANIFEST_DIRS["tag"] / "deployment.yaml")[0]
    volumes = deploy["spec"]["template"]["spec"]["volumes"]
    assert volumes[0]["emptyDir"] == {}


def test_mag_recreate_and_pvc():
    deploy = deployments(MANIFEST_DIRS["mag"] / "deployment.yaml")[0]
    assert deploy["spec"]["strategy"]["type"] == "Recreate"
    pod_spec = deploy["spec"]["template"]["spec"]
    volume = pod_spec["volumes"][0]
    assert volume["persistentVolumeClaim"]["claimName"] == "ag-mag-data"
    mount = pod_spec["containers"][0]["volumeMounts"][0]
    assert mount["mountPath"] == "/data"
    env = {item["name"]: item for item in pod_spec["containers"][0]["env"]}
    assert env["MAG_DB_PATH"]["value"] == "/data/mag.db"


def test_mag_pvc_shape():
    docs = load_docs(MANIFEST_DIRS["mag"] / "pvc.yaml")
    assert len(docs) == 1
    pvc = docs[0]
    assert pvc["kind"] == "PersistentVolumeClaim"
    assert pvc["metadata"]["name"] == "ag-mag-data"
    assert pvc["metadata"]["namespace"] == "rag"
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert pvc["spec"]["storageClassName"] == "standard-rwo"
    assert pvc["spec"]["resources"]["requests"]["storage"] == "1Gi"


def test_no_plaintext_secret_values():
    for path in MANIFEST_FILES:
        for doc in load_docs(path):
            for container in doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
                for item in container.get("env", []):
                    if "KEY" in item["name"] or "SECRET" in item["name"] or "TOKEN" in item["name"]:
                        assert "value" not in item, f"plaintext secret in {path}: {item['name']}"


KUBECTL = shutil.which("kubectl")


def _cluster_reachable():
    if KUBECTL is None:
        return False
    try:
        result = subprocess.run(
            [KUBECTL, "cluster-info", "--request-timeout=5s"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


CLUSTER_OK = _cluster_reachable()


@pytest.mark.skipif(KUBECTL is None, reason="kubectl not on PATH; skipping client dry-run")
@pytest.mark.skipif(not CLUSTER_OK, reason="kubectl apply needs API discovery; no cluster reachable, skipping")
@pytest.mark.parametrize("path", MANIFEST_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_kubectl_client_dry_run(path):
    result = subprocess.run(
        [KUBECTL, "apply", "--dry-run=client", "--request-timeout=20s", "-f", str(path)],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, f"dry-run failed for {path}:\n{result.stderr}"
    assert "dry run" in result.stdout
