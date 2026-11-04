"""Vendor update-check & broadcast announcements — opt-in and privacy-preserving.

Self-hosted RackMon never phones home by default. When an admin explicitly
enables update checks (the ``updates`` setting, or ``RACKMON_UPDATE_CHECK_ENABLED``),
the app periodically fetches a small **static** JSON manifest from the vendor —
a plain ``GET`` that sends no telemetry, no instance data, nothing but the request
itself — and surfaces:

  * whether a newer version is available (+ release notes / download URL), and
  * an optional broadcast announcement from the vendor (e.g. a security notice
    or a "what's new" message) that the UI shows as a dismissible banner.

Everything degrades gracefully: the feature is a no-op unless enabled, network
or parse errors never raise (they just yield "no update info"), and results are
cached so a dashboard full of operators cannot hammer the manifest.

Manifest shape (all fields optional except ``version``)::

    {
      "stable": {                     # keyed by channel, or put fields at top level
        "version": "1.2.0",
        "notes": "Faster polling, SLA export fixes.",
        "url": "https://rackmon.app/changelog.html",
        "published_at": "2026-09-01",
        "min_supported": "1.0.0"
      },
      "announcement": {               # optional, shown to everyone
        "id": "2026-09-flash-sale",
        "level": "info",              # info | success | warning | critical
        "title": "RackMon 1.2 is out",
        "body": "Upgrade for the new SLA PDF templates.",
        "link": "https://rackmon.app/changelog.html"
      }
    }
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

from sqlalchemy.orm import Session

from ..config import APP_VERSION, get_settings
from ..models import Setting

# El dominio del fabricante es rackmon.APP. Hasta la 1.2.10 esto apuntaba a
# rackmon.io, que no es nuestro y que ni siquiera resuelve, y nada en el proyecto
# lo sobreescribia: ni el .env.example, ni compose, ni la documentacion. O sea que
# una instalacion que encendiera la comprobacion de actualizaciones preguntaba a
# un dominio inexistente y no recibia NADA — ni avisos de version nueva ni
# anuncios de seguridad. Es el unico canal que tenemos para avisar a quien ya
# tiene el producto instalado de que hay algo que arreglar, y estaba cortado.
#
# Hay una segunda razon para corregirlo: rackmon.io esta libre. Quien lo registre
# le sirve un manifiesto a toda instalacion que siga con el valor por defecto, y
# los anuncios se pintan con su titulo y su enlace dentro del panel de RackMon.
DEFAULT_MANIFEST_URL = "https://rackmon.app/updates/manifest.json"
_CACHE_TTL_SECONDS = 6 * 3600
_HTTP_TIMEOUT = 4.0

_cache: dict = {"at": 0.0, "url": None, "data": None}
_lock = threading.Lock()


def parse_semver(v: str) -> tuple[int, int, int]:
    """Best-effort (major, minor, patch) from a leading ``X.Y.Z``. Pre-release /
    build suffixes (``-mvp``, ``+build``) are ignored for ordering, and missing
    components default to 0 so ``"1.2"`` and ``"v1"`` still compare sanely."""
    core = str(v or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = (core.split(".") + ["0", "0", "0"])[:3]
    out: list[int] = []
    for p in parts:
        digits = "".join(ch for ch in p if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return out[0], out[1], out[2]


def is_newer(latest: str, current: str) -> bool:
    return parse_semver(latest) > parse_semver(current)


def _config(db: Session) -> tuple[bool, str, str]:
    """Resolve (enabled, manifest_url, channel) from the DB ``updates`` setting,
    falling back to environment settings, then the vendor default URL."""
    row = db.get(Setting, "updates")
    cfg = row.value if row and isinstance(row.value, dict) else {}
    s = get_settings()
    enabled = bool(cfg.get("enabled", s.update_check_enabled))
    url = str(cfg.get("manifest_url") or s.update_manifest_url or DEFAULT_MANIFEST_URL)
    channel = str(cfg.get("channel") or "stable")
    return enabled, url, channel


def decision_pendiente(db: Session) -> bool:
    """¿Todavía no ha decidido nadie si RackMon puede buscar actualizaciones?

    RackMon no hace una sola llamada al exterior hasta que un administrador
    responde, y por eso el proyecto puede seguir diciendo que no llama a casa
    por su cuenta. Pero una instalación a la que nunca se le preguntó es una
    instalación a la que no se puede avisar: hasta la 1.2.9 había un fallo que
    dejaba leer cualquier fichero sin tener cuenta, y la única forma de
    contarlo fue la descripción de Docker Hub.

    Se da por respondida si el ajuste guardado trae un "enabled" explícito, o si
    quien despliega lo dejó decidido por entorno. Lo que no vale como respuesta
    es la ausencia de todo: eso es que nadie ha mirado todavía.
    """
    row = db.get(Setting, "updates")
    cfg = row.value if row and isinstance(row.value, dict) else {}
    if "enabled" in cfg:
        return False
    return not get_settings().update_check_enabled


def _fetch(url: str) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"RackMon/{APP_VERSION}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310 (opt-in, admin-set URL)
        payload = resp.read().decode("utf-8")
    data = json.loads(payload)
    return data if isinstance(data, dict) else None


def _manifest(url: str, force: bool = False) -> dict | None:
    now = time.monotonic()
    with _lock:
        fresh = (
            _cache["data"] is not None
            and _cache["url"] == url
            and (now - _cache["at"]) < _CACHE_TTL_SECONDS
        )
        if fresh and not force:
            return _cache["data"]
    try:
        data = _fetch(url)
    except Exception:
        data = None
    with _lock:
        if data is not None:
            _cache.update(at=now, url=url, data=data)
            return data
        # On failure keep serving the last good manifest for this URL, if any.
        return _cache["data"] if _cache["url"] == url else None


def get_update_status(db: Session, force: bool = False) -> dict:
    """Return the current update/announcement status. Safe to call often;
    never raises. When disabled, only the current version is reported."""
    enabled, url, channel = _config(db)
    status: dict = {
        "current": APP_VERSION,
        "enabled": enabled,
        # Se devuelve siempre, tambien con la comprobacion apagada: es justo
        # cuando esta apagada cuando hay que preguntar.
        "decision_pending": decision_pendiente(db),
        "channel": channel,
        "checked": False,
        "latest": None,
        "update_available": False,
        "unsupported": False,
        "notes": None,
        "download_url": None,
        "published_at": None,
        "announcement": None,
    }
    if not enabled:
        return status

    data = _manifest(url, force=force)
    if not data:
        return status
    status["checked"] = True

    node = data.get(channel)
    if not isinstance(node, dict):
        node = data
    latest = str(node.get("version") or node.get("latest") or "").strip()
    if latest:
        status["latest"] = latest
        status["update_available"] = is_newer(latest, APP_VERSION)
        status["notes"] = node.get("notes")
        status["download_url"] = node.get("url") or node.get("download_url")
        status["published_at"] = node.get("published_at")
        min_supported = node.get("min_supported")
        if min_supported and parse_semver(APP_VERSION) < parse_semver(str(min_supported)):
            status["unsupported"] = True

    ann = data.get("announcement") or node.get("announcement")
    if isinstance(ann, dict) and ann.get("id") and (ann.get("title") or ann.get("body")):
        status["announcement"] = {
            "id": str(ann["id"]),
            "level": str(ann.get("level") or "info"),
            "title": ann.get("title"),
            "body": ann.get("body"),
            "link": ann.get("link"),
        }
    return status


def _reset_cache_for_tests() -> None:
    with _lock:
        _cache.update(at=0.0, url=None, data=None)
