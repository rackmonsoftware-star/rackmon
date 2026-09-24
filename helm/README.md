# RackMon Helm chart

Deploys RackMon (API + dedicated poller + TimescaleDB + Redis) to Kubernetes,
with an Ingress, TLS, and a HorizontalPodAutoscaler for the API tier.

> Note: this chart is provided as standard, ready-to-use Kubernetes manifests.
> It has not been rendered/deployed in the build environment — validate against
> your cluster with `helm lint` and `helm template` before installing.

## Prerequisites
- A Kubernetes cluster and `kubectl`/`helm` configured.
- A built RackMon image pushed to a registry (see `backend/Dockerfile`):
  ```
  docker build -f backend/Dockerfile -t ghcr.io/your-org/rackmon:1.1.0 .
  docker push ghcr.io/your-org/rackmon:1.1.0
  ```

## Install
```bash
helm install rackmon deploy/helm/rackmon \
  --set image.repository=ghcr.io/your-org/rackmon \
  --set image.tag=1.1.0 \
  --set secrets.jwtSecret=$(openssl rand -hex 32) \
  --set secrets.masterKey=$(openssl rand -hex 32) \
  --set secrets.dbPassword=$(openssl rand -hex 24) \
  --set ingress.host=rackmon.example.com
```

Or copy `values.yaml`, edit it, and `helm install rackmon deploy/helm/rackmon -f my-values.yaml`.

## Architecture on Kubernetes
- **api** Deployment (autoscaled 2–6 pods) serves the SPA + API; polling disabled.
- **poller** Deployment (single replica) runs `python -m app.worker` — the SNMP
  polling, alert engine, scheduler, and weekly reports.
- **postgres** (TimescaleDB) with a PersistentVolumeClaim.
- **redis** provisioned for multi-pod realtime fan-out.
- **Ingress** (+ optional TLS secret) exposes the API service.

Use `secrets.existingSecret` to reference secrets from an external manager
instead of passing them to Helm.
