#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFESTS="${REPO_ROOT}/k8s/showcases"
NAMESPACE="rag"

usage() {
    cat <<'EOF'
Usage: demo.sh <command> <method> [--force|--yes]

One-at-a-time manager for the augmentation showcases on the cluster.

Commands:
  up <method>           Apply the method's manifests (refuses if another
                        showcase is active, unless --force is given)
  down <method>         Delete the method's manifests (keeps MAG's PVC)
  status                Show showcase deployments/pods in the rag namespace
  port-forward <method> Forward the service to its local demo port
  purge mag             Delete MAG's PVC (all memories) after confirmation

Methods: tag (port 8091), cag (port 8092), mag (port 8093)

Examples:
  demo.sh up tag
  demo.sh port-forward tag
  demo.sh status
  demo.sh down tag
  demo.sh purge mag --yes
EOF
}

need_kubectl() {
    if ! command -v kubectl >/dev/null 2>&1; then
        echo "error: kubectl not found on PATH; install it or fix your kubeconfig first" >&2
        exit 3
    fi
}

port_for() {
    case "$1" in
        tag) echo 8091 ;;
        cag) echo 8092 ;;
        mag) echo 8093 ;;
    esac
}

active_showcase() {
    kubectl get deploy -n "$NAMESPACE" -l ag-showcase \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null \
        | sed 's/^ag-//' | head -1 || true
}

cmd_up() {
    local method="$1" force="${2:-}"
    local current
    current="$(active_showcase)"
    if [ -n "$current" ] && [ "$current" != "$method" ] && [ "$force" != "--force" ]; then
        echo "refusing: showcase '${current}' is already active; one at a time."
        echo "run: demo.sh down ${current} && demo.sh up ${method}  (or: demo.sh up ${method} --force)"
        exit 1
    fi
    echo "+ kubectl apply -f ${MANIFESTS}/${method}/"
    kubectl apply -f "${MANIFESTS}/${method}/"
    echo
    echo "showcase '${method}' is now active."
    echo "watch it:   kubectl -n ${NAMESPACE} rollout status deploy/ag-${method}"
    echo "use it:     demo.sh port-forward ${method}"
    echo "cleanup:    demo.sh down ${method}"
}

cmd_down() {
    local method="$1"
    echo "+ kubectl delete -f ${MANIFESTS}/${method}/deployment.yaml"
    kubectl delete -f "${MANIFESTS}/${method}/deployment.yaml"
    if [ "$method" = "mag" ]; then
        echo "keeping PVC ag-mag-data: stored memories survive 'down'."
        echo "delete them with: demo.sh purge mag"
    fi
}

cmd_status() {
    echo "+ kubectl get deploy,pods -n ${NAMESPACE} -l ag-showcase -o wide"
    kubectl get deploy,pods -n "${NAMESPACE}" -l ag-showcase -o wide
    local current
    current="$(active_showcase)"
    if [ -n "$current" ]; then
        echo "active showcase: ${current}"
    else
        echo "no showcase active"
    fi
}

cmd_port_forward() {
    local method="$1" port
    port="$(port_for "$method")"
    echo "forwarding svc/ag-${method} to http://localhost:${port}"
    echo "try it:  curl -s -X POST http://localhost:${port}/chat -H 'Content-Type: application/json' -d '{\"question\": \"...\"}'"
    echo "+ kubectl port-forward -n ${NAMESPACE} svc/ag-${method} ${port}:80"
    kubectl port-forward -n "${NAMESPACE}" "svc/ag-${method}" "${port}:80"
}

cmd_purge() {
    local method="$1" yes="${2:-}"
    if [ "$method" != "mag" ]; then
        echo "purge only applies to mag (tag/cag keep no persistent state)" >&2
        usage
        exit 2
    fi
    if [ "$yes" != "--yes" ]; then
        local reply=""
        read -r -p "delete PVC ag-mag-data and ALL stored memories? [y/N] " reply || true
        case "$reply" in
            y | Y | yes) ;;
            *) echo "aborted; memories kept"; exit 1 ;;
        esac
    fi
    echo "+ kubectl delete pvc ag-mag-data -n ${NAMESPACE}"
    kubectl delete pvc ag-mag-data -n "${NAMESPACE}"
    echo "all MAG memories deleted."
}

main() {
    if [ $# -eq 0 ]; then
        usage
        exit 2
    fi
    local command="$1" method="${2:-}" flag="${3:-}"
    case "$command" in
        status)
            if [ $# -ne 1 ]; then
                usage
                exit 2
            fi
            need_kubectl
            cmd_status
            return
            ;;
        up | down | port-forward | purge) ;;
        *)
            usage
            exit 2
            ;;
    esac
    case "$method" in
        tag | cag | mag) ;;
        *)
            usage
            exit 2
            ;;
    esac
    if [ $# -gt 3 ]; then
        usage
        exit 2
    fi
    case "$flag" in
        "" | --force | --yes) ;;
        *)
            usage
            exit 2
            ;;
    esac
    need_kubectl
    case "$command" in
        up) cmd_up "$method" "$flag" ;;
        down) cmd_down "$method" ;;
        port-forward) cmd_port_forward "$method" ;;
        purge) cmd_purge "$method" "$flag" ;;
    esac
}

main "$@"
