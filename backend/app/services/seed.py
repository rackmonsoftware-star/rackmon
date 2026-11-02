"""Idempotent seeding of users and demo data."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import DEV_VIEWER_PASSWORD, get_settings
from ..crypto import encrypt
from ..models import (
    AlertRule,
    Device,
    MetricCatalog,
    Role,
    Severity,
    User,
)
from ..security import hash_password, verify_password

log = logging.getLogger("rackmon.seed")

# (name, label, unit, oid, interval)
#
# SOLO para el parque simulado de la demo, donde el colector ni mira el OID.
#
# Son OID de CISCO (empresa 9). Hasta la 1.2.3 esto era además el catálogo de
# arranque de CUALQUIER equipo creado sin métricas, incluido todo lo que entraba
# por el descubrimiento de red: un Dell, un HPE o un PDU de APC se llevaban el
# catálogo de un switch Cisco y devolvían "no hay datos" sin un solo error que lo
# explicara. Ese camino ahora pasa por `templates.catalogo_por_defecto()`, que
# elige la plantilla del fabricante o, si no lo conoce, la neutral de
# ENTITY-SENSOR-MIB. No uses esta lista para hardware real.
_DEFAULT_METRICS = [
    ("temp_cpu", "CPU temperature", "\u00b0C", "1.3.6.1.4.1.9.9.13.1.3.1.3.1", 15),
    ("temp_inlet", "Inlet temperature", "\u00b0C", "1.3.6.1.4.1.9.9.13.1.3.1.3.2", 15),
    ("cpu_load", "CPU load", "%", "1.3.6.1.4.1.9.9.109.1.1.1.1.5.1", 30),
    ("mem_used", "Memory used", "%", "1.3.6.1.4.1.9.9.48.1.1.1.5.1", 30),
    ("fan_rpm", "Fan speed", "rpm", "1.3.6.1.4.1.9.9.13.1.4.1.3.1", 30),
]

# Demo fleet: mixed vendors across two racks, one deliberately hot.
_DEMO_DEVICES = [
    dict(name="core-sw-01", ip="10.20.0.11", vendor="Cisco", model="C9300",
         rack="RACK-A", position_u=42, size_u=1, tags=["network", "production"]),
    dict(name="esxi-node-01", ip="10.20.0.21", vendor="Dell", model="R750",
         rack="RACK-A", position_u=38, size_u=2, tags=["compute", "production"]),
    dict(name="esxi-node-02", ip="10.20.0.22", vendor="HPE", model="DL380",
         rack="RACK-A", position_u=36, size_u=2, tags=["compute", "production", "hot"]),
    dict(name="nas-01", ip="10.20.0.31", vendor="Synology", model="RS3621",
         rack="RACK-A", position_u=30, size_u=2, tags=["storage"]),
    dict(name="ups-01", ip="10.20.0.41", vendor="APC", model="SRT5K",
         rack="RACK-A", position_u=2, size_u=3, tags=["power", "critical"]),
    dict(name="edge-sw-01", ip="10.20.1.11", vendor="MikroTik", model="CRS354",
         rack="RACK-B", position_u=42, size_u=1, tags=["network"]),
    dict(name="build-node-01", ip="10.20.1.21", vendor="Supermicro", model="AS-2124",
         rack="RACK-B", position_u=20, size_u=2, tags=["compute", "ci"]),
]

# Reglas que se siembran SIEMPRE, en cualquier instalación.
#
# Hasta ahora las únicas reglas del producto eran _DEMO_RULES, y vivían dentro
# del `if not seed_demo_data: return`. O sea que una instalación limpia —la que
# recomiendan .env.example, docs.html y el chart de Helm, todos diciendo "ponlo
# en false para un arranque limpio"— arrancaba con CERO reglas.
#
# Lo que eso significa, medido: equipo real a 41 °C durante media hora, 120
# barridos, y ni un correo, ni un webhook, ni una fila en /api/v1/alerts. Y
# mientras tanto la tarjeta del panel se pinta en ROJO, porque el color lo decide
# classify() y no el motor de alertas. El cliente ve rojo, da por hecho que le
# avisarían, y nadie le avisa nunca. Un producto de monitorización mudo que
# parece que funciona es peor que uno que no arranca.
#
# Los cortes son los que el producto ya publica en sus guías y los que usa
# classify(), así que el color del panel y la alerta dicen por fin lo mismo.
_REGLAS_BASE = [
    dict(name="Inlet temperature warning", scope_type="global", metric="temp_inlet",
         operator=">", threshold=27.0, for_seconds=120, severity=Severity.warning.value,
         throttle_seconds=1800),
    dict(name="Inlet temperature critical", scope_type="global", metric="temp_inlet",
         operator=">", threshold=32.0, for_seconds=60, severity=Severity.critical.value,
         throttle_seconds=900),
    dict(name="CPU temperature critical", scope_type="global", metric="temp_cpu",
         operator=">", threshold=80.0, for_seconds=60, severity=Severity.critical.value,
         throttle_seconds=900),
    dict(name="Fan stalled", scope_type="global", metric="fan_rpm",
         operator="<", threshold=500.0, for_seconds=0, severity=Severity.critical.value,
         throttle_seconds=900),
    # Un equipo que deja de contestar. Tres minutos de silencio continuado antes
    # de avisar: un tiempo de espera suelto o un reinicio de agente SNMP no
    # merecen despertar a nadie, pero un rack entero mudo todo un fin de semana
    # sí. Es crítica a propósito, porque mientras dura no sabemos la temperatura
    # de ese equipo: no es que esté bien, es que no lo sabemos. Y al ser crítica
    # cuenta como indisponibilidad en el informe de SLA, donde hasta ahora un
    # equipo muerto el mes entero figuraba con un 100 % de disponibilidad.
    dict(name="Device unreachable", scope_type="global", metric="device_reachable",
         operator="<", threshold=1.0, for_seconds=180, severity=Severity.critical.value,
         throttle_seconds=3600),
]


def _reglas_de_arranque(db: Session) -> int:
    """Siembra las reglas base si no están. Idempotente por nombre.

    No toca una regla que ya exista, ni siquiera para "corregirla": si el
    operador bajó un umbral o la desactivó, esa es su decisión y se respeta.
    """
    puestas = 0
    for spec in _REGLAS_BASE:
        existe = db.scalar(select(AlertRule).where(AlertRule.name == spec["name"]))
        if existe is not None:
            continue
        db.add(AlertRule(**spec))
        puestas += 1
    if puestas:
        log.info(
            "sembradas %s regla(s) de alerta de arranque: sin ellas el motor de "
            "alertas no puede disparar nada y la instalación sería muda",
            puestas,
        )
    return puestas


_DEMO_RULES = [
    dict(name="CPU temperature warning", scope_type="global", metric="temp_cpu",
         operator=">", threshold=70.0, for_seconds=0, severity=Severity.warning.value,
         throttle_seconds=900),
    dict(name="Inlet temperature high (production)", scope_type="tag", scope_ref="production",
         metric="temp_inlet", operator=">", threshold=32.0, for_seconds=0,
         severity=Severity.warning.value, throttle_seconds=900),
]


def _ensure_user(db: Session, email: str, password: str, role: Role) -> None:
    exists = db.scalar(select(User).where(User.email == email))
    if exists:
        return
    db.add(
        User(email=email, password_hash=hash_password(password), role=role.value, is_active=True)
    )
    log.info("seeded user %s (%s)", email, role.value)


def _administrador_inicial(db: Session, settings) -> None:
    """La cuenta de administrador de arranque, solo si NO hay ya un administrador.

    Antes esto era `_ensure_user(admin_email, ...)` a secas: crear la cuenta si no
    existía **ese correo exacto**. La pregunta correcta no es si está ese correo,
    sino si la instalación ya tiene quien la administre.

    Las dos maneras normales de quitarse de encima la cuenta de fábrica son
    ponerle tu propio correo o crear la tuya y borrar aquella. En ambos casos el
    correo de fábrica deja de existir, así que el arranque siguiente la volvía a
    crear: activa, con rol admin y con `RACKMON_ADMIN_PASSWORD` — que por omisión
    es la de fábrica, publicada en la documentación. El operador ya había hecho
    los deberes y no tenía ningún motivo para volver a mirar la lista de usuarios.

    Y el guardián de producción no lo tapaba: solo rechaza una `admin_password`
    de fábrica cuando `RACKMON_ENVIRONMENT=production`, y ese valor es
    "development" por omisión.

    Se cuentan los administradores **sin mirar si están activos**. Un
    administrador desactivado sigue siendo una cuenta de la instalación, y
    resucitar la de fábrica porque alguien la desactivó convertiría eso mismo en
    una puerta de atrás.
    """
    ya_hay = db.scalar(
        select(func.count()).select_from(User).where(User.role == Role.admin.value)
    )
    if ya_hay:
        return
    _ensure_user(db, settings.admin_email, settings.admin_password, Role.admin)


def _cuenta_de_solo_lectura(db: Session, settings) -> None:
    """La cuenta de solo lectura, solo si su contraseña no es la publicada.

    ``viewer@rackmon.io`` / ``viewer12345`` aparece impresa en rackmon.app como el
    acceso de la demo. Hasta ahora esta cuenta se creaba SIEMPRE y activa, y el
    comando de instalación de la portada no pone ninguna contraseña, así que toda
    instalación que siguiera las instrucciones quedaba con un usuario válido cuya
    contraseña está publicada en internet. Con rol viewer se lee el parque entero:
    nombres, IPs, hostnames, racks, telemetría e histórico. Y el guardián de
    producción no lo veía, porque solo audita jwt_secret, master_key y
    admin_password.

    Reglas:
      - Contraseña propia (cualquier cosa distinta de la de fábrica): se crea
        normalmente. Es una cuenta legítima.
      - Contraseña de fábrica y modo demo: se crea. Es justo para lo que existe
        la demo pública, y ahí no hay nada que proteger.
      - Contraseña de fábrica sin modo demo: NO se crea. Y si ya existe de una
        versión anterior, se DESACTIVA al arrancar y se le anula la contraseña —
        pero solo si esa contraseña sigue siendo literalmente la publicada. Si el
        operador la cambió por la interfaz, no se toca nada.
      - Y hay vuelta: definir RACKMON_VIEWER_PASSWORD reactiva esa misma cuenta
        con la contraseña indicada. En la 1.2.3 el log prometía esto y no pasaba
        nada al hacerlo; la cuenta se quedaba muerta para siempre.
    """
    import secrets

    propia = settings.viewer_password != DEV_VIEWER_PASSWORD
    existente = db.scalar(select(User).where(User.email == settings.viewer_email))

    # --- El operador ha dicho cuál es la contraseña de esa cuenta ---------------
    #
    # Aquí NO vale _ensure_user: sale en cuanto la fila existe, sin tocar nada. Esa
    # era la trampa de la 1.2.3: el log decía "para volver a usarla, arranca con
    # RACKMON_VIEWER_PASSWORD=..." y hacerlo no servía de nada — la cuenta seguía
    # desactivada, seguía guardando el hash de la contraseña publicada, y a partir
    # del segundo arranque ni siquiera se registraba el motivo. Medido: ocho
    # arranques, la cuenta nunca volvía.
    #
    # Definir la variable es una instrucción explícita sobre esa cuenta, así que se
    # obedece: existe, con esa contraseña y activa. Se sube token_version para que
    # cualquier sesión anterior deje de valer.
    if propia or settings.demo_mode:
        if existente is None:
            _ensure_user(db, settings.viewer_email, settings.viewer_password, Role.viewer)
            return
        cambia_clave = not verify_password(settings.viewer_password, existente.password_hash)
        if cambia_clave or not existente.is_active:
            existente.password_hash = hash_password(settings.viewer_password)
            existente.is_active = True
            existente.token_version = (existente.token_version or 0) + 1
            log.warning(
                "cuenta de solo lectura %s puesta al día con RACKMON_VIEWER_PASSWORD: "
                "activa y con la contraseña que has configurado. Las sesiones anteriores "
                "dejan de valer.",
                settings.viewer_email,
            )
        return

    # --- Sin contraseña propia: la de fábrica está publicada --------------------
    if existente is None:
        log.info(
            "cuenta de solo lectura %s no creada: su contraseña sería la de fábrica, que "
            "está publicada. Define RACKMON_VIEWER_PASSWORD si la quieres.",
            settings.viewer_email,
        )
        return

    if existente.is_active and verify_password(DEV_VIEWER_PASSWORD, existente.password_hash):
        existente.is_active = False
        # Y se DESTRUYE la credencial publicada, no solo se desactiva la cuenta.
        # Desactivar sin más dejaba el hash de "viewer12345" guardado: bastaba con
        # que un administrador pulsara "Activar" en el panel para reabrir el
        # agujero al instante. Comprobado por HTTP: PATCH is_active=true y el login
        # con la contraseña publicada volvía a entrar. Con una contraseña aleatoria
        # que no conoce nadie, ese botón ya no reabre nada.
        existente.password_hash = hash_password(secrets.token_urlsafe(32))
        existente.token_version = (existente.token_version or 0) + 1
        log.warning(
            "DESACTIVADA la cuenta %s y anulada su contraseña: seguía con la de fábrica, "
            "que está publicada en rackmon.app y permitía leer todo el parque. Para tener "
            "una cuenta de solo lectura, arranca con RACKMON_VIEWER_PASSWORD=<la tuya> "
            "(esta misma cuenta se reactivará con ella), o crea un usuario desde "
            "Administración → Usuarios.",
            settings.viewer_email,
        )


def seed_all() -> None:
    settings = get_settings()
    with session_scope_local() as db:
        _administrador_inicial(db, settings)
        _cuenta_de_solo_lectura(db, settings)
        # ANTES del corte por seed_demo_data: una instalación limpia también
        # necesita poder avisar. Es lo único que este producto tiene que hacer.
        _reglas_de_arranque(db)

        if not settings.seed_demo_data:
            return

        device_count = db.scalar(select(func.count()).select_from(Device)) or 0
        if device_count > 0:
            return  # demo data already present

        admin = db.scalar(select(User).where(User.email == settings.admin_email))
        for spec in _DEMO_DEVICES:
            device = Device(
                name=spec["name"], ip=spec["ip"], hostname=spec["name"],
                snmp_version="2c", snmp_community_enc=encrypt("public"),
                vendor=spec["vendor"], model=spec["model"], rack=spec["rack"],
                position_u=spec["position_u"], size_u=spec["size_u"],
                tags=spec["tags"], enabled=True,
                created_by=admin.id if admin else None,
            )
            db.add(device)
            db.flush()
            for name, label, unit, oid, interval in _DEFAULT_METRICS:
                # NAS/UPS/switch have no CPU load/mem in this demo; keep temps + fan.
                if name in ("cpu_load", "mem_used") and "compute" not in spec["tags"] \
                        and "ci" not in spec["tags"]:
                    continue
                db.add(
                    MetricCatalog(
                        device_id=device.id, name=name, label=label, unit=unit,
                        oid=oid, poll_interval_s=interval, enabled=True,
                    )
                )
        for rule in _DEMO_RULES:
            db.add(AlertRule(**rule))
        log.info("seeded %s demo devices and %s rules", len(_DEMO_DEVICES), len(_DEMO_RULES))


# Local import wrapper to avoid a circular import at module load.
from contextlib import contextmanager  # noqa: E402


@contextmanager
def session_scope_local():
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
