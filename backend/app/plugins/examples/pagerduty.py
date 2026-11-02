"""Example channel plugin: forward alerts to a PagerDuty-style webhook.

Enable by installing/placing this module and setting, e.g.:
    RACKMON_PLUGINS_MODULES=app.plugins.examples.pagerduty
    RACKMON_PLUGIN_PAGERDUTY_URL=https://events.pagerduty.com/...

The actual HTTP POST needs a real endpoint and is not exercised in tests.
"""
from __future__ import annotations

import os

from ...plugins import register_channel


@register_channel("pagerduty")
def send(alert, device, config) -> None:  # pragma: no cover - network/example
    import httpx

    url = os.environ.get("RACKMON_PLUGIN_PAGERDUTY_URL")
    if not url:
        raise RuntimeError("RACKMON_PLUGIN_PAGERDUTY_URL not set")
    httpx.post(url, json={
        "summary": alert.message,
        "severity": alert.severity,
        "source": device.ip,
        "device": device.name,
    }, timeout=10.0).raise_for_status()
