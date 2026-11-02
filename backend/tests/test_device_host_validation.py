"""El destino SNMP de un dispositivo (auditoría 24-sep).

"Añadir dispositivo" es la acción principal del producto. Un error de dedo en la
dirección no puede tragarse en silencio: deja un equipo que no responde nunca y
nadie sabe por qué.
"""
from __future__ import annotations

import pytest

from app.schemas import DeviceCreate, DeviceUpdate


def _crear(**over):
    datos = dict(name="equipo", ip="10.0.0.1", snmp_version="2c", snmp_community="x")
    datos.update(over)
    return DeviceCreate(**datos)


# --- lo que debe seguir aceptándose ----------------------------------------

@pytest.mark.parametrize("destino", [
    "10.0.0.1",                 # IPv4
    "192.168.1.255",            # IPv4 en el borde
    "0.0.0.0",                  # IPv4 válida aunque rara
    "2001:db8::1",              # IPv6
    "::1",                      # IPv6 corta
    "switch-01",                # nombre de host corto
    "switch-01.corp.local",     # nombre cualificado
    "rack1.planta2.empresa.es", # nombre largo
])
def test_valid_targets_are_accepted(destino):
    """SNMP puede apuntar a una IP o a un nombre: los dos son legítimos."""
    assert _crear(ip=destino).ip == destino


# --- lo que debe rechazarse ------------------------------------------------

@pytest.mark.parametrize("malo", [
    "192.168.1.300",    # parece IPv4 y no lo es -> error de dedo típico
    "999.999.999.999",
    "10.0.0.256",
    "1.2.3.999",
])
def test_things_that_look_like_an_ipv4_but_are_not(malo):
    """El caso que motivó esto: se aceptaba y el equipo quedaba muerto."""
    with pytest.raises(ValueError, match="IPv4"):
        _crear(ip=malo)


@pytest.mark.parametrize("malo", ["", "   ", "con espacios", "a" * 256])
def test_empty_spaced_or_absurdly_long_targets(malo):
    with pytest.raises(ValueError):
        _crear(ip=malo)


# --- el hueco de la actualización ------------------------------------------

def test_update_validates_the_target_too():
    """Se podía crear con una IP buena y luego cambiarla a cualquier cosa,
    saltándose el control de creación por completo."""
    with pytest.raises(ValueError, match="IPv4"):
        DeviceUpdate(ip="192.168.1.300")
    with pytest.raises(ValueError):
        DeviceUpdate(ip="con espacios")


def test_update_without_touching_the_ip_is_fine():
    """Actualizar otra cosa no puede exigir mandar la IP."""
    assert DeviceUpdate(name="otro nombre").ip is None
    assert DeviceUpdate(ip="10.0.0.9").ip == "10.0.0.9"
