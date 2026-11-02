#!/usr/bin/env bash
#
# Real Kubernetes: spins up a local cluster with kind, builds the RackMon image,
# `helm install`s the chart, and waits for the pods to actually become Ready.
# The same deploy CI runs on every push, on a cluster you can poke at afterwards.
#
# Requirements: Docker running. kind + helm are installed automatically if absent.
# Usage:        bash scripts/verify-k8s.sh
# Cleanup:      kind delete cluster --name rackmon
#
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "ERROR: Docker is required (Docker Desktop or engine)."; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon is not running."; exit 1; }

OS="$(uname | tr '[:upper:]' '[:lower:]')"; ARCH="$(uname -m)"; [ "$ARCH" = "x86_64" ] && ARCH=amd64; [ "$ARCH" = "aarch64" ] && ARCH=arm64

if ! command -v kind >/dev/null; then
  echo "==> Installing kind"
  curl -fsSLo /tmp/kind "https://kind.sigs.k8s.io/dl/latest/kind-${OS}-${ARCH}"
  chmod +x /tmp/kind && sudo mv /tmp/kind /usr/local/bin/kind
fi
if ! command -v helm >/dev/null; then
  echo "==> Installing helm"
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

echo "==> Creating kind cluster 'rackmon'"
kind create cluster --name rackmon 2>/dev/null || echo "(cluster already exists)"

echo "==> Building the backend image and loading it into the cluster"
docker build -t rackmon:dev -f backend/Dockerfile .
kind load docker-image rackmon:dev --name rackmon

echo "==> helm install"
helm upgrade --install rackmon ./deploy/helm/rackmon \
  --set image.repository=rackmon \
  --set image.tag=dev \
  --set image.pullPolicy=Never \
  --set ingress.enabled=false \
  --wait --timeout 5m

echo ""
echo "==> Cluster state"
kubectl get pods -o wide
kubectl wait --for=condition=available --timeout=300s deployment --all
echo ""
echo "PASS: the chart deployed to a real Kubernetes cluster and the pods are Ready."
echo "Clean up with:  kind delete cluster --name rackmon"
