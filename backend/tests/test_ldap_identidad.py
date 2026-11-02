"""Dos usuarios del directorio no pueden acabar en la misma cuenta.

El codigo decidia la identidad local asi:

    email = str(entry[attr].value) if attr in entry else username

y esa guarda no protegia de nada. ldap3 2.9.1 crea la conexion con
`return_empty_attributes=True` por defecto, asi que un atributo PEDIDO en el
search() pero que la entrada no tiene vuelve igualmente, con valor None.
`attr in entry` daba verdadero y `str(None)` es la cadena "None".

Consecuencia: TODOS los usuarios sin `mail` en el directorio compartian una
unica cuenta local llamada "none". Y provision_user asciende la cuenta a
administrador en cuanto UNO de ellos pertenece al grupo de admins, asi que
bastaba un solo administrador despistado sin correo para que todos los demas
entraran con permisos de administrador, viendo ademas la sesion del anterior.
"""
from __future__ import annotations

from app.services import ldap_auth


class _Atributo:
    """Lo que devuelve ldap3 para un atributo pedido pero ausente: existe, vale None."""

    def __init__(self, value):
        self.value = value


class _Entrada:
    """Imita el comportamiento de ldap3 con return_empty_attributes=True."""

    def __init__(self, atributos):
        self._a = atributos

    def __contains__(self, k):
        return k in self._a          # presente aunque este vacio: eso es el fallo

    def __getitem__(self, k):
        return _Atributo(self._a[k])


def test_un_usuario_sin_correo_no_se_llama_none():
    e = _Entrada({"mail": None})
    assert ldap_auth._identidad(e, "mail", "jdoe") == "jdoe", (
        "el usuario sin correo acaba con la identidad literal 'None'"
    )


def test_dos_usuarios_sin_correo_no_comparten_cuenta():
    """El corazon del fallo."""
    a = ldap_auth._identidad(_Entrada({"mail": None}), "mail", "jdoe")
    b = ldap_auth._identidad(_Entrada({"mail": None}), "mail", "asmith")
    assert a != b, (
        f"jdoe y asmith comparten la identidad local {a!r}: entran en la misma "
        "cuenta, y si uno es del grupo de administradores lo son los dos"
    )


def test_un_correo_vacio_tampoco_colisiona():
    a = ldap_auth._identidad(_Entrada({"mail": ""}), "mail", "jdoe")
    b = ldap_auth._identidad(_Entrada({"mail": "   "}), "mail", "asmith")
    assert a == "jdoe" and b == "asmith"


def test_el_texto_none_literal_tampoco_pasa():
    """Por si un directorio guarda de verdad la cadena 'None' o 'null'."""
    for basura in ("None", "none", "NULL", "nil"):
        assert ldap_auth._identidad(_Entrada({"mail": basura}), "mail", "jdoe") == "jdoe"


def test_un_correo_de_verdad_se_respeta():
    e = _Entrada({"mail": "jdoe@corp.com"})
    assert ldap_auth._identidad(e, "mail", "jdoe") == "jdoe@corp.com"


def test_un_atributo_multivalor_toma_el_primero():
    e = _Entrada({"mail": ["jdoe@corp.com", "john.doe@corp.com"]})
    assert ldap_auth._identidad(e, "mail", "jdoe") == "jdoe@corp.com"


def test_el_atributo_que_no_existe_cae_al_nombre_de_usuario():
    e = _Entrada({})
    assert ldap_auth._identidad(e, "mail", "jdoe") == "jdoe"


def test_de_punta_a_punta_dos_usuarios_sin_correo_son_dos_cuentas(db):
    """Y que provision_user no los junte tampoco."""
    cfg = {"admin_group": "cn=admins", "default_role": "viewer"}
    u1 = ldap_auth.provision_user(
        db, {"email": ldap_auth._identidad(_Entrada({"mail": None}), "mail", "jdoe"),
             "groups": []}, cfg)
    u2 = ldap_auth.provision_user(
        db, {"email": ldap_auth._identidad(_Entrada({"mail": None}), "mail", "asmith"),
             "groups": ["cn=admins"]}, cfg)

    assert u1.id != u2.id, "los dos usuarios del directorio son la misma cuenta local"
    assert u2.role == "admin", "el que si esta en el grupo debe ser admin"
    assert u1.role == "viewer", (
        "el usuario corriente ha heredado permisos de administrador porque "
        "comparte cuenta con uno que si los tiene"
    )
