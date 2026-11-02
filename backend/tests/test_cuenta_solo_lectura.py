"""La cuenta de solo lectura y su contraseña de fábrica.

``viewer@rackmon.io`` / ``viewer12345`` estuvo impresa en rackmon.app como el
acceso de la demo, y el comando de instalación de la portada no ponía ninguna
contraseña. Resultado: toda instalación que siguiera las instrucciones quedaba
con un usuario válido cuya contraseña estaba publicada en internet, y con rol
viewer se lee el parque entero — nombres, IPs, hostnames, racks, telemetría e
histórico. El guardián de producción no lo veía porque solo audita jwt_secret,
master_key y admin_password.

Estas pruebas fijan el comportamiento nuevo para que no pueda volver.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import DEV_VIEWER_PASSWORD, get_settings
from app.models import Role, User
from app.security import hash_password, verify_password
from app.services.seed import seed_all


@pytest.fixture()
def de_fabrica(monkeypatch):
    """Una instalación normal que no puso contraseña: se queda con la de fábrica."""
    s = get_settings()
    monkeypatch.setattr(s, "viewer_password", DEV_VIEWER_PASSWORD, raising=False)
    monkeypatch.setattr(s, "demo_mode", False, raising=False)
    return s


def _viewer(db) -> User | None:
    return db.scalar(select(User).where(User.email == get_settings().viewer_email))


def test_no_se_crea_la_cuenta_con_la_contrasena_publicada(db, de_fabrica):
    db.query(User).filter(User.email == de_fabrica.viewer_email).delete()
    db.commit()

    seed_all()

    assert _viewer(db) is None, (
        "se ha creado viewer@rackmon.io con la contraseña que está publicada en la web"
    )


def test_una_cuenta_vieja_con_la_contrasena_publicada_se_desactiva(db, de_fabrica):
    """El caso de las 22 instalaciones que ya existen: al actualizar, se cierra."""
    existente = _viewer(db)
    if existente is None:
        existente = User(
            email=de_fabrica.viewer_email,
            password_hash=hash_password(DEV_VIEWER_PASSWORD),
            role=Role.viewer.value,
            is_active=True,
        )
        db.add(existente)
    else:
        existente.password_hash = hash_password(DEV_VIEWER_PASSWORD)
        existente.is_active = True
    db.commit()

    seed_all()
    db.expire_all()

    quedo = _viewer(db)
    assert quedo is not None, "la cuenta no se borra, se desactiva"
    assert quedo.is_active is False, (
        "la cuenta seguía activa con una contraseña publicada en internet"
    )


def test_el_login_deja_de_funcionar_despues_de_desactivarla(client: TestClient, db, de_fabrica):
    existente = _viewer(db)
    if existente is None:
        db.add(
            User(
                email=de_fabrica.viewer_email,
                password_hash=hash_password(DEV_VIEWER_PASSWORD),
                role=Role.viewer.value,
                is_active=True,
            )
        )
    else:
        existente.password_hash = hash_password(DEV_VIEWER_PASSWORD)
        existente.is_active = True
    db.commit()

    # Antes del arreglo, esto entraba.
    seed_all()

    r = client.post(
        "/api/v1/auth/login",
        json={"email": de_fabrica.viewer_email, "password": DEV_VIEWER_PASSWORD},
    )
    assert r.status_code != 200, "la credencial publicada sigue dando sesión"


def test_no_se_toca_una_cuenta_cuya_contrasena_cambio_el_operador(db, de_fabrica):
    """Si el operador ya la cambió por la interfaz, esa cuenta es suya."""
    suya = "una-contrasena-que-eligio-el-operador"
    existente = _viewer(db)
    if existente is None:
        existente = User(
            email=de_fabrica.viewer_email,
            password_hash=hash_password(suya),
            role=Role.viewer.value,
            is_active=True,
        )
        db.add(existente)
    else:
        existente.password_hash = hash_password(suya)
        existente.is_active = True
    db.commit()

    seed_all()
    db.expire_all()

    quedo = _viewer(db)
    assert quedo is not None and quedo.is_active is True
    assert verify_password(suya, quedo.password_hash)


def test_con_contrasena_propia_la_cuenta_se_crea_y_entra(client: TestClient, db, monkeypatch):
    propia = "mi-propia-contrasena-de-solo-lectura"
    s = get_settings()
    monkeypatch.setattr(s, "viewer_password", propia, raising=False)
    monkeypatch.setattr(s, "demo_mode", False, raising=False)
    db.query(User).filter(User.email == s.viewer_email).delete()
    db.commit()

    seed_all()

    r = client.post("/api/v1/auth/login", json={"email": s.viewer_email, "password": propia})
    assert r.status_code == 200


def test_la_demo_publica_si_la_necesita(db, monkeypatch):
    """La demo entra sin credenciales a una cuenta de solo lectura: ahí no hay nada
    que proteger y la cuenta tiene que existir."""
    s = get_settings()
    monkeypatch.setattr(s, "viewer_password", DEV_VIEWER_PASSWORD, raising=False)
    monkeypatch.setattr(s, "demo_mode", True, raising=False)
    db.query(User).filter(User.email == s.viewer_email).delete()
    db.commit()

    seed_all()
    db.expire_all()

    quedo = _viewer(db)
    assert quedo is not None and quedo.is_active is True
    assert quedo.role == Role.viewer.value


def test_repetirlo_no_cambia_nada(db, de_fabrica):
    """seed_all() corre en cada arranque: tiene que ser idempotente."""
    seed_all()
    primero = _viewer(db)
    estado1 = None if primero is None else primero.is_active
    seed_all()
    db.expire_all()
    segundo = _viewer(db)
    estado2 = None if segundo is None else segundo.is_active
    assert estado1 == estado2


# --------------------------------------------------------------------------
# La vuelta atrás: que el remedio que imprime el log FUNCIONE de verdad
#
# La 1.2.3 desactivaba la cuenta y escribía en el log "para volver a usarla,
# arranca con RACKMON_VIEWER_PASSWORD=<la tuya>". Hacerlo no servía de nada:
# _ensure_user sale en cuanto la fila existe, así que la cuenta seguía
# desactivada, seguía guardando el hash de la contraseña publicada, y desde el
# segundo arranque ni siquiera se registraba el motivo. Reproducido con ocho
# arranques reales antes de arreglarlo.
# --------------------------------------------------------------------------
def test_definir_la_contrasena_reactiva_la_cuenta_desactivada(client: TestClient, db, monkeypatch):
    """El camino que el log promete, de punta a punta."""
    s = get_settings()
    # 1. Una instalación que viene de 1.2.2: cuenta activa con la de fábrica.
    db.query(User).filter(User.email == s.viewer_email).delete()
    db.add(
        User(
            email=s.viewer_email,
            password_hash=hash_password(DEV_VIEWER_PASSWORD),
            role=Role.viewer.value,
            is_active=True,
        )
    )
    db.commit()

    # 2. Primer arranque de 1.2.3: se desactiva.
    monkeypatch.setattr(s, "viewer_password", DEV_VIEWER_PASSWORD, raising=False)
    monkeypatch.setattr(s, "demo_mode", False, raising=False)
    seed_all()
    db.expire_all()
    assert _viewer(db).is_active is False

    # 3. El operador hace lo que dice el log.
    mia = "la-contrasena-que-he-elegido-yo"
    monkeypatch.setattr(s, "viewer_password", mia, raising=False)
    seed_all()
    db.expire_all()

    quedo = _viewer(db)
    assert quedo.is_active is True, "el remedio que imprime el log no reactiva la cuenta"
    assert verify_password(mia, quedo.password_hash), "no ha quedado con MI contraseña"

    r = client.post("/api/v1/auth/login", json={"email": s.viewer_email, "password": mia})
    assert r.status_code == 200, "la cuenta dice estar activa pero no deja entrar"


def test_al_desactivarla_se_anula_la_contrasena_publicada(db, de_fabrica):
    """Desactivar no basta: si queda el hash de la contraseña publicada, un
    administrador que pulse «Activar» en el panel reabre el agujero al instante."""
    db.query(User).filter(User.email == de_fabrica.viewer_email).delete()
    db.add(
        User(
            email=de_fabrica.viewer_email,
            password_hash=hash_password(DEV_VIEWER_PASSWORD),
            role=Role.viewer.value,
            is_active=True,
        )
    )
    db.commit()

    seed_all()
    db.expire_all()

    quedo = _viewer(db)
    assert quedo.is_active is False
    assert not verify_password(DEV_VIEWER_PASSWORD, quedo.password_hash), (
        "sigue guardada la contraseña publicada: un «Activar» en el panel la reabre"
    )


def test_reactivarla_a_mano_no_reabre_el_agujero(client: TestClient, db, de_fabrica, admin_headers):
    """El bucle medido: el panel activa, el arranque desactiva, y vuelta. Con la
    contraseña anulada, activarla ya no sirve de nada a quien conozca la publicada."""
    db.query(User).filter(User.email == de_fabrica.viewer_email).delete()
    db.add(
        User(
            email=de_fabrica.viewer_email,
            password_hash=hash_password(DEV_VIEWER_PASSWORD),
            role=Role.viewer.value,
            is_active=True,
        )
    )
    db.commit()
    seed_all()
    db.expire_all()

    # Un administrador pulsa «Activar».
    uid = _viewer(db).id
    r = client.patch(
        f"/api/v1/admin/users/{uid}", headers=admin_headers, json={"is_active": True}
    )
    assert r.status_code in (200, 204), r.text

    # La contraseña publicada ya no entra.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": de_fabrica.viewer_email, "password": DEV_VIEWER_PASSWORD},
    )
    assert r.status_code != 200, "la contraseña publicada vuelve a entrar tras «Activar»"
