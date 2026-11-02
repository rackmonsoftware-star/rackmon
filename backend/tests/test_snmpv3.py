"""SNMPv3: credential encode/decode, USM building, and device wiring."""
from __future__ import annotations

import json

from app.models import Device
from app.services import snmpv3

CFG = {
    "security_name": "v3user", "auth_protocol": "SHA", "auth_key": "authkey123",
    "priv_protocol": "AES", "priv_key": "privkey123",
}


def test_encode_decode_roundtrip():
    assert snmpv3.decode(snmpv3.encode(CFG)) == CFG
    assert snmpv3.decode(None) is None
    assert snmpv3.decode("") is None


def test_security_level():
    assert snmpv3.security_level(CFG) == "authPriv"
    assert snmpv3.security_level({"auth_protocol": "SHA", "priv_protocol": "none"}) == "authNoPriv"
    assert snmpv3.security_level({"auth_protocol": "none", "priv_protocol": "none"}) == "noAuthNoPriv"


def test_build_usm_sets_username():
    assert str(snmpv3.build_usm(CFG).userName) == "v3user"
    noauth = {"security_name": "plain", "auth_protocol": "none", "priv_protocol": "none"}
    assert str(snmpv3.build_usm(noauth).userName) == "plain"


def test_create_device_with_v3_credentials(client, operator_headers, db):
    r = client.post("/api/v1/devices", headers=operator_headers, json={
        "name": "v3dev", "ip": "10.9.0.9", "snmp_version": "3", "snmpv3": CFG,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["has_snmpv3"] is True
    assert body["has_community"] is False  # no community given
    # Secrets must never appear in the API output.
    assert "authkey123" not in json.dumps(body)

    dev = db.get(Device, body["id"])
    assert snmpv3.decode(dev.snmpv3_enc)["security_name"] == "v3user"


def test_regular_device_has_no_v3(client, operator_headers):
    r = client.post("/api/v1/devices", headers=operator_headers,
                    json={"name": "v2dev", "ip": "10.9.0.10"})
    assert r.json()["has_snmpv3"] is False


# --- Collector wiring: the real SNMP collector must actually USE v3 creds ---- #
def test_collector_uses_usm_for_v3_device():
    from pysnmp.hlapi.asyncio import UsmUserData

    from app.services.collector import SnmpCollector

    dev = Device(name="v3", ip="10.0.0.9", snmp_version="3", snmpv3_enc=snmpv3.encode(CFG))
    auth = SnmpCollector()._build_auth(dev)
    assert isinstance(auth, UsmUserData)
    assert str(auth.userName) == "v3user"


def test_collector_uses_community_for_v2c_device():
    from pysnmp.hlapi.asyncio import CommunityData

    from app.crypto import encrypt
    from app.services.collector import SnmpCollector

    dev = Device(name="v2", ip="10.0.0.10", snmp_version="2c", snmp_community_enc=encrypt("public"))
    auth = SnmpCollector()._build_auth(dev)
    assert isinstance(auth, CommunityData)


def test_collector_v3_without_credentials_raises():
    import pytest

    from app.services.collector import SnmpCollector

    dev = Device(name="v3bad", ip="10.0.0.11", snmp_version="3", snmpv3_enc=None)
    with pytest.raises(RuntimeError):
        SnmpCollector()._build_auth(dev)
