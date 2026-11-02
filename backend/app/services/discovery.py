"""SNMP discovery: expand a target (CIDR / range / single IP) and probe hosts.

In simulator mode (default, no hardware) a deterministic subset of addresses
"respond", so the feature is demoable end-to-end. In real mode each host is
probed over SNMP for its system name; that path needs reachable devices.
"""
from __future__ import annotations

import ipaddress
import logging
from concurrent.futures import ThreadPoolExecutor

from ..config import get_settings

log = logging.getLogger("rackmon.discovery")

MAX_HOSTS = 512

# Cuántos equipos se prueban a la vez. Antes se probaban de uno en uno, y cada
# dirección que no contesta se come el tiempo de espera entero: una /24 con la
# mitad apagada tardaba más de cuatro minutos, bloqueando un hilo del servidor
# todo ese rato. Dos o tres escaneos a la vez y la API entera dejaba de
# responder — y la forma normal de usar esto es precisamente escanear una red
# entera. Con 32 a la vez, los 512 del tope caben en unos veinte segundos.
SONDEOS_A_LA_VEZ = 32


def expand(target: str) -> list[str]:
    """Accepts 'a.b.c.d/nn' (CIDR), 'a.b.c.x-y' (last-octet range), or a single IP."""
    target = target.strip()
    if "/" in target:
        net = ipaddress.ip_network(target, strict=False)
        # Bound the network BEFORE materializing it: a value like 10.0.0.0/8 would
        # otherwise build ~16M strings (memory/CPU DoS) before scan() slices to MAX_HOSTS.
        if net.num_addresses > MAX_HOSTS + 2:
            raise ValueError(f"network too large; narrow it to <= {MAX_HOSTS} hosts")
        return [str(ip) for ip in net.hosts()]
    if "-" in target:
        base, _, tail = target.rpartition(".")
        lo_s, _, hi_s = tail.partition("-")
        lo, hi = int(lo_s), int(hi_s)
        if lo > hi or lo < 0 or hi > 255:
            raise ValueError("invalid range")
        return [f"{base}.{i}" for i in range(lo, hi + 1)]
    ipaddress.ip_address(target)  # validate
    return [target]


def _simulated_probe(ip: str) -> dict | None:
    # Deterministic: roughly a third of hosts "respond".
    last = int(ip.split(".")[-1])
    if last % 3 == 0:
        return {"sysname": f"host-{ip.replace('.', '-')}", "vendor": "SimVendor"}
    return None


def _snmp_probe(ip: str, community: str, version: str) -> dict | None:  # pragma: no cover - hardware
    from pysnmp.hlapi import (
        CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine,
        UdpTransportTarget, getCmd,
    )

    mp_model = 0 if version == "1" else 1
    it = getCmd(
        SnmpEngine(),
        CommunityData(community, mpModel=mp_model),
        UdpTransportTarget((ip, 161), timeout=1.0, retries=0),
        ContextData(),
        ObjectType(ObjectIdentity("1.3.6.1.2.1.1.5.0")),  # sysName
    )
    err_ind, err_stat, _, var_binds = next(it)
    if err_ind or err_stat:
        return None
    sysname = str(var_binds[0][1]) if var_binds else ip
    return {"sysname": sysname or ip, "vendor": None}


def scan(target: str, community: str = "public", version: str = "2c",
         limit: int = MAX_HOSTS) -> list[dict]:
    hosts = expand(target)[:limit]
    use_sim = get_settings().poller_use_simulator

    if use_sim:
        # El simulador no toca la red: en serie es instantáneo y así el resultado
        # es idéntico vuelta tras vuelta.
        return [{"ip": ip, **info} for ip in hosts if (info := _simulated_probe(ip))]

    def _uno(ip: str):
        try:
            return ip, _snmp_probe(ip, community, version)
        except Exception as exc:  # pragma: no cover - depende de la red
            # Una dirección que falle raro no puede llevarse por delante el
            # escaneo entero: se anota y se sigue con las demás.
            log.debug("sondeo de %s fallido: %s", ip, exc)
            return ip, None

    with ThreadPoolExecutor(max_workers=min(SONDEOS_A_LA_VEZ, max(1, len(hosts)))) as pool:
        resultados = list(pool.map(_uno, hosts))
    # Se conserva el orden de la red, que es como lo espera ver quien escanea.
    return [{"ip": ip, **info} for ip, info in resultados if info]
