# Updates & vendor announcements

RackMon is self-hosted: it runs on **your** server and, by default, never phones
home. This document explains the optional, privacy-preserving update system and
how to keep an instance current — "like an app that updates itself" — without
giving up that control.

## How it works

There are two independent layers:

1. **Update *notifications* (in-app).** When an admin turns this on, RackMon
   periodically fetches a small **static JSON file** from the vendor
   (`https://rackmon.app/updates/manifest.json`) — a plain `GET` that sends **no
   telemetry, no instance data, nothing but the request**. If a newer version
   exists, admins see an "Update available v1.4 → v1.5" banner with release
   notes. The same file can carry a broadcast **announcement** (e.g. a security
   notice or "what's new") shown to everyone as a dismissible banner.

   - Off by default. Enable in **Admin → Settings → Updates**, or set
     `RACKMON_UPDATE_CHECK_ENABLED=true`.
   - Result is cached ~6h; failures degrade silently (never blocks the UI).
   - Endpoint: `GET /api/v1/update-status`.

2. **Update *delivery* (the actual new code).** RackMon ships as a container
   image, so upgrading is pulling a new image and restarting — the standard,
   auditable, roll-back-able way to update self-hosted software. You choose
   between manual and automatic:

   | Mode | How | Who controls timing |
   |------|-----|--------------------|
   | Manual | `docker compose pull && docker compose up -d` | You |
   | Auto (Docker) | [Watchtower](https://containrrr.dev/watchtower/) watching `rackmon/rackmon:latest` | You (opt-in) |
   | Auto (Kubernetes) | Flux/Argo image automation, or `imagePullPolicy: Always` + a rollout | You (opt-in) |

> We deliberately **do not** push code to your server on our schedule. Silent
> remote updates would break change-control and the "your box, your data"
> promise. You opt into auto-delivery, and you can always pin a version.

### Enable automatic delivery with Watchtower (Docker)

```bash
docker run -d --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower --interval 3600 rackmon
```

Watchtower pulls a new `rackmon/rackmon:latest` when you publish one and
restarts the container. Pin a specific tag (e.g. `rackmon/rackmon:1.2.0`)
instead of `latest` if you want to gate upgrades yourself.

### Pinning / rolling back

Run a specific tag: `image: rackmon/rackmon:1.2.0`. Data lives in your database
(and volumes), so rolling back the image is safe as long as you haven't run a
newer schema migration.

## For the vendor: cutting a release

Releases are prepared with `scripts/release.py`, which bumps the app version and
updates the published manifest. Nothing ships until you push the image and
publish the manifest.

```bash
# 1. Prepare the release (bumps APP_VERSION + website/updates/manifest.json)
python scripts/release.py 1.2.0 --notes "Faster polling, SLA PDF fixes." \
    --url https://rackmon.app/changelog.html

# 2. Build & push the image
docker build -t rackmon/rackmon:1.2.0 -f backend/Dockerfile .
docker tag rackmon/rackmon:1.2.0 rackmon/rackmon:latest
docker push rackmon/rackmon:1.2.0 && docker push rackmon/rackmon:latest

# 3. Publish the manifest (deploy website/updates/manifest.json to the update URL)
#    and the marketing site — it reads the same file to show the latest version.
```

Broadcast a message to all installs (no version change):

```bash
python scripts/release.py --announce "Security notice" \
    --announce-body "Please upgrade to 1.2.1." --announce-level warning \
    --announce-link https://rackmon.app/changelog.html
# ...then publish website/updates/manifest.json.
python scripts/release.py --clear-announcement   # when it's no longer relevant
```

### Manifest shape

```json
{
  "stable": { "version": "1.2.0", "notes": "…", "url": "https://…",
              "published_at": "2026-09-01", "min_supported": "1.0.0" },
  "beta":   { "version": "1.3.0-rc1", "notes": "…", "url": "https://…" },
  "announcement": { "id": "2026-09-notice", "level": "warning",
                    "title": "…", "body": "…", "link": "https://…" }
}
```

`min_supported` lets you flag very old instances as unsupported (the API returns
`unsupported: true`). `announcement.id` is how the UI remembers a dismissal —
change it for each new message.
