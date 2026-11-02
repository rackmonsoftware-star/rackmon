"""El administrador de fábrica no debe resucitar en cada arranque.

`seed_all()` corre en cada arranque y llama a `_ensure_user(admin_email, ...)`,
que crea la cuenta si no encuentra **ese correo exacto**. Visto así parece
inofensivo —"si no está, créala"—, pero la pregunta correcta no es si está esa
cuenta, sino si la instalación ya tiene administrador.

Las dos formas normales de deshacerse de la cuenta de fábrica son cambiarle el
correo por el tuyo o crear la tuya y borrar aquella. En ambos casos el correo de
fábrica deja de existir, así que el siguiente reinicio la vuelve a crear: activa,
con rol admin y con la contraseña de fábrica, que está publicada. El operador ya
ha hecho los deberes y no tiene por qué volver a mirar la lista de usuarios.

El guardián de producción no cubre esto. Solo se queja de `admin_password` de
fábrica cuando `RACKMON_ENVIRONMENT=production`, y ese valor es
"development" por omisión.
"""
from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import verify_password
from app.services.seed import seed_all

from conftest import ADMIN

FABRICA = ADMIN["email"]
CLAVE_DE_FABRICA = ADMIN["password"]


def _admins() -> list[tuple[str, bool]]:
    with SessionLocal() as db:
        filas = db.scalars(select(User).where(User.role == "admin")).all()
        return [(u.email, verify_password(CLAVE_DE_FABRICA, u.password_hash)) for u in filas]


def test_renombrar_al_admin_no_lo_resucita(client, admin_headers):
    """El caso de un operador ordenado: se pone su propio correo y reinicia."""
    yo = client.get("/api/v1/admin/users", headers=admin_headers).json()
    mio = next(u for u in yo if u["email"] == FABRICA)

    r = client.patch(f"/api/v1/admin/users/{mio['id']}",
                     json={"email": "ops@empresa-real.example"}, headers=admin_headers)
    assert r.status_code == 200, r.text

    seed_all()   # el reinicio

    admins = _admins()
    correos = [e for e, _ in admins]
    assert FABRICA not in correos, (
        f"el administrador de fábrica ha vuelto al reiniciar: {admins}"
    )
    # Y no ha aparecido NINGUNA cuenta nueva: la suya sigue siendo la única, con la
    # contraseña que ella tuviera. Lo que no puede pasar es que el reinicio añada
    # un administrador más que el operador no ha pedido.
    assert correos == ["ops@empresa-real.example"], f"administradores tras reiniciar: {admins}"


def test_borrar_al_admin_de_fabrica_no_lo_resucita(client, admin_headers):
    """El otro camino: creo el mío, borro el de fábrica, reinicio."""
    r = client.post("/api/v1/admin/users",
                    json={"email": "jefe@empresa-real.example",
                          "password": "una-clave-larga-propia", "role": "admin"},
                    headers=admin_headers)
    assert r.status_code == 201, r.text

    usuarios = client.get("/api/v1/admin/users", headers=admin_headers).json()
    fabrica = next(u for u in usuarios if u["email"] == FABRICA)
    # No se puede borrar la cuenta con la que estoy dentro, así que entro con la mía.
    nuevo = client.post("/api/v1/auth/login",
                        json={"email": "jefe@empresa-real.example",
                              "password": "una-clave-larga-propia"}).json()
    cab = {"Authorization": f"Bearer {nuevo['access_token']}"}
    assert client.delete(f"/api/v1/admin/users/{fabrica['id']}", headers=cab).status_code == 204

    seed_all()   # el reinicio

    admins = _admins()
    assert FABRICA not in [e for e, _ in admins], (
        f"el administrador de fábrica ha vuelto al reiniciar: {admins}"
    )


def test_una_instalacion_limpia_si_recibe_su_admin():
    """La otra mitad del contrato: sin usuarios, la cuenta se crea igual que antes."""
    with SessionLocal() as db:
        for u in db.scalars(select(User)).all():
            db.delete(u)
        db.commit()

    seed_all()

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == FABRICA))
    assert admin is not None and admin.role == "admin" and admin.is_active
