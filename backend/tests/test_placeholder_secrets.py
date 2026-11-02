"""Secretos de relleno de plantilla (auditoría 24-sep).

La plantilla de Unraid traía `CHANGE-ME-openssl-rand-hex-32` prerrellenado en la
clave de firma y en la clave maestra, y NO fijaba el entorno, así que esas
instalaciones arrancaban en modo desarrollo y el guardián solo avisaba en el
registro. Esa cadena está publicada: cualquiera podía firmarse un token de
administrador y descifrar las credenciales SNMP guardadas.
"""
from __future__ import annotations

import pytest

from app.config import Settings, production_safety_check


def _ajustes(**over) -> Settings:
    base = dict(
        environment="development",
        jwt_secret="a" * 48,
        master_key="b" * 48,
        admin_password="c" * 24,
    )
    base.update(over)
    return Settings(**base)


@pytest.mark.parametrize("campo", ["jwt_secret", "master_key", "admin_password"])
def test_template_placeholder_is_refused_even_in_development(campo):
    """En desarrollo los valores por defecto SÍ valen (para eso están), pero un
    'CHANGE-ME' de plantilla no es legítimo en ningún entorno."""
    s = _ajustes(**{campo: "CHANGE-ME-openssl-rand-hex-32"})
    with pytest.raises(RuntimeError, match="placeholder"):
        production_safety_check(s)


@pytest.mark.parametrize("relleno", [
    "CHANGE-ME-openssl-rand-hex-32",
    "change-me",
    "ChangeMe123",
    "replace-me-with-a-real-key",
    "tu-clave-aqui",
])
def test_placeholder_variants_are_all_caught(relleno):
    with pytest.raises(RuntimeError, match="placeholder"):
        production_safety_check(_ajustes(jwt_secret=relleno))


def test_the_error_explains_the_master_key_consequence():
    """Cambiar la clave maestra deja ilegibles las credenciales ya guardadas.
    Si no se avisa, el usuario lo descubre cuando sus equipos dejan de sondearse."""
    with pytest.raises(RuntimeError) as e:
        production_safety_check(_ajustes(master_key="CHANGE-ME-openssl-rand-hex-32"))
    texto = str(e.value)
    assert "openssl rand -hex 32" in texto, "hay que decirle CÓMO generar uno"
    assert "re-enter" in texto.lower(), "hay que avisar de que perderá las credenciales"


def test_real_secrets_start_fine_in_any_environment():
    for entorno in ("development", "production", "test"):
        production_safety_check(_ajustes(environment=entorno))  # no levanta


def test_development_defaults_still_work_on_a_laptop():
    """No rompemos el arranque sin configurar en local: para eso existen."""
    from app.config import DEV_JWT_SECRET, DEV_MASTER_KEY

    production_safety_check(_ajustes(jwt_secret=DEV_JWT_SECRET, master_key=DEV_MASTER_KEY))


def test_development_defaults_are_still_refused_in_production():
    from app.config import DEV_JWT_SECRET

    with pytest.raises(RuntimeError, match="insecure default"):
        production_safety_check(_ajustes(environment="production", jwt_secret=DEV_JWT_SECRET))
