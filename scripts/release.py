#!/usr/bin/env python3
"""Cut a RackMon release: bump the app version and update the public update
manifest so the website and every opted-in instance learn about it.

This is a *vendor* tool. It never touches customer installs — it only prepares
the artifacts you then publish (container image + the manifest.json served at
your update URL). Actual delivery is pull-based and customer-opt-in (see
docs/AUTO-UPDATE.md).

Usage:
    python scripts/release.py 1.2.0 --notes "Faster polling, SLA PDF fixes." \
        --channel stable --url https://rackmon.app/changelog.html

    python scripts/release.py --announce "1.2 is out" \
        --announce-body "Upgrade for the new SLA templates." \
        --announce-level info --announce-link https://rackmon.app/changelog.html

The update manifest is not part of this repository: it belongs to whoever hosts
the update URL, so this script looks for it beside the repo as well. After
running, deploy the updated manifest to that URL and push the container image
tags (see the printed checklist).
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "backend" / "app" / "config.py"


def _find_manifest() -> pathlib.Path:
    """Locate the update manifest, which lives outside this repository.

    The site is deployed from Cloudflare and is deliberately not committed here:
    it carries an IndexNow key that must never be published. In the maintainer's
    working tree it sits beside the repo, so the two candidates are tried in
    turn and the first that exists wins. If neither does, the caller gets a
    clear error instead of a file quietly created in the wrong place.
    """
    for candidate in (
        ROOT / "website" / "updates" / "manifest.json",
        ROOT.parent / "cloudflare" / "web" / "updates" / "manifest.json",
    ):
        if candidate.is_file():
            return candidate
    # Nothing found: return the expected location so the error names it.
    return ROOT.parent / "cloudflare" / "web" / "updates" / "manifest.json"


MANIFEST = _find_manifest()
CHART = ROOT / "deploy" / "helm" / "rackmon" / "Chart.yaml"
VALUES = ROOT / "deploy" / "helm" / "rackmon" / "values.yaml"
PACKAGE = ROOT / "frontend" / "package.json"

SEMVER_CORE = re.compile(r"^\d+\.\d+\.\d+")


def _read_current_version() -> str:
    text = CONFIG.read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("Could not find APP_VERSION in config.py")
    return m.group(1)


def _bump_config_version(new_version: str) -> None:
    text = CONFIG.read_text(encoding="utf-8")
    text, n = re.subn(r'(APP_VERSION\s*=\s*")[^"]+(")', rf"\g<1>{new_version}\g<2>", text)
    if n != 1:
        sys.exit("Failed to rewrite APP_VERSION")
    # newline="\n" or Windows rewrites every line ending in the file, turning a
    # one-character version bump into a whole-file diff.
    CONFIG.write_text(text, encoding="utf-8", newline="\n")


def _bump_companions(new_version: str) -> list[str]:
    """Los otros sitios donde esta escrita la version.

    El chart llego a declarar `appVersion: 1.0.0-mvp` e `image.tag: "1.0.0"` con
    el producto en la 1.2.10, asi que un `helm install` desde el repositorio
    instalaba una imagen de dos versiones atras —sin el arreglo de seguridad— y
    el despliegue funcionaba, que es lo que lo hacia dificil de ver. Se bajan
    todos de una, y `backend/tests/test_la_version_cuadra.py` falla si alguno se
    queda descolgado.
    """
    tocados = []
    for ruta, patron in (
        (CHART, r'(^appVersion:\s*")[^"]+(")'),
        (VALUES, r'(^\s+tag:\s*")[^"]+(")'),
        (PACKAGE, r'(^\s*"version":\s*")[^"]+(")'),
    ):
        if not ruta.exists():
            continue
        texto = ruta.read_text(encoding="utf-8")
        nuevo, n = re.subn(patron, rf"\g<1>{new_version}\g<2>", texto, count=1, flags=re.M)
        if n != 1:
            sys.exit(f"No pude reescribir la version en {ruta.relative_to(ROOT)}")
        ruta.write_text(nuevo, encoding="utf-8", newline="\n")
        tocados.append(str(ruta.relative_to(ROOT)))
    # El chart tiene ademas su propia version de empaquetado, que sube con el.
    if CHART.exists():
        texto = CHART.read_text(encoding="utf-8")
        nuevo, n = re.subn(r"(^version:\s*)\S+", rf"\g<1>{new_version}", texto, count=1, flags=re.M)
        if n == 1:
            CHART.write_text(nuevo, encoding="utf-8", newline="\n")
    return tocados


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _save_manifest(data: dict) -> None:
    MANIFEST.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def announcement_id(today: str, title: str, limit: int = 32) -> str:
    """Build the announcement id every installation stores to remember it was seen.

    The trim happens *after* the cut, not before. Trimming first and cutting
    second lets the cut land on a separator, which is how the 1.3.0 announcement
    ended up identified as ``2026-11-02-rackmon-is-free-and-open-source-``.
    """
    return f"{today}-{re.sub(r'[^a-z0-9]+', '-', title.lower())[:limit].strip('-')}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Cut a RackMon release / publish an announcement.")
    ap.add_argument("version", nargs="?", help="new version, e.g. 1.2.0")
    ap.add_argument("--notes", default="", help="release notes shown in the update banner")
    ap.add_argument("--channel", default="stable", choices=["stable", "beta"])
    ap.add_argument("--url", default="https://rackmon.app/changelog.html",
                    help="download / release URL. El dominio es rackmon.APP: hasta la "
                         "1.2.10 este valor por defecto decia rackmon.io, que no es nuestro, "
                         "y cortar una release sin --url lo escribia en el manifiesto.")
    ap.add_argument("--min-supported", default=None, help="oldest version still supported")
    ap.add_argument("--date", default=None, help="published_at (YYYY-MM-DD); defaults to today")
    # Announcement-only mode (no version bump)
    ap.add_argument("--announce", default=None, help="announcement title (broadcast to all installs)")
    ap.add_argument("--announce-body", default="")
    ap.add_argument("--announce-level", default="info", choices=["info", "success", "warning", "critical"])
    ap.add_argument("--announce-link", default=None)
    ap.add_argument("--clear-announcement", action="store_true")
    args = ap.parse_args()

    today = args.date or datetime.date.today().isoformat()
    manifest = _load_manifest()

    if args.version:
        if not SEMVER_CORE.match(args.version):
            sys.exit("version must start with X.Y.Z")
        current = _read_current_version()
        print(f"Bumping app version {current} -> {args.version}")
        _bump_config_version(args.version)
        companeros = _bump_companions(args.version)
        node = manifest.setdefault(args.channel, {})
        node["version"] = args.version
        node["notes"] = args.notes
        node["url"] = args.url
        node["published_at"] = today
        if args.min_supported:
            node["min_supported"] = args.min_supported

    if args.clear_announcement:
        manifest["announcement"] = None
    elif args.announce:
        manifest["announcement"] = {
            "id": announcement_id(today, args.announce),
            "level": args.announce_level,
            "title": args.announce,
            "body": args.announce_body,
            "link": args.announce_link,
        }

    if not args.version and not args.announce and not args.clear_announcement:
        ap.error("nothing to do: pass a version and/or --announce / --clear-announcement")

    _save_manifest(manifest)

    print("\nUpdated:")
    print(f"  - {CONFIG.relative_to(ROOT)} (APP_VERSION)" if args.version else "  - (no version change)")
    if args.version:
        for c in companeros:
            print(f"  - {c}")
    print(f"  - {MANIFEST.relative_to(ROOT)}")
    print("\nNext steps (nothing has shipped yet):")
    if args.version:
        print(f"  1. Build & push the image:  docker build -t rackmon/rackmon:{args.version} -f backend/Dockerfile .")
        print(f"                              docker tag rackmon/rackmon:{args.version} rackmon/rackmon:latest")
        print(f"                              docker push rackmon/rackmon:{args.version} && docker push rackmon/rackmon:latest")
        print("  2. Commit & tag:            git commit -am 'release: {v}' && git tag v{v}".format(v=args.version))
    print(f"  {'3' if args.version else '1'}. Publish the manifest:    deploy {MANIFEST} to your update URL")
    print("     Instances with update checks ON will show the banner within their cache window (~6h).")


if __name__ == "__main__":
    main()
