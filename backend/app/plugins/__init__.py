"""Extensibility: a small plugin registry (Fase 4).

Third parties can add notification channels without touching core code, either
by importing this package and using the ``@register_channel`` decorator, or by
installing a module and listing it in RACKMON_PLUGINS_MODULES so it is imported
at startup. Registered channels are invoked by the notifier alongside the
built-in ones, each isolated so a failing plugin can't break delivery.

A channel plugin is a callable: ``fn(alert, device, config) -> None`` that
sends the notification (and may raise on failure).
"""
from __future__ import annotations

import importlib
import logging
from typing import Callable

log = logging.getLogger("rackmon.plugins")

ChannelPlugin = Callable[..., None]

_CHANNEL_PLUGINS: dict[str, ChannelPlugin] = {}


def register_channel(name: str) -> Callable[[ChannelPlugin], ChannelPlugin]:
    """Decorator to register a notification-channel plugin under ``name``."""
    def decorator(fn: ChannelPlugin) -> ChannelPlugin:
        _CHANNEL_PLUGINS[name] = fn
        log.info("registered channel plugin: %s", name)
        return fn
    return decorator


def channel_plugins() -> dict[str, ChannelPlugin]:
    return dict(_CHANNEL_PLUGINS)


def clear_channel_plugins() -> None:
    """Reset the registry (used by tests)."""
    _CHANNEL_PLUGINS.clear()


def load_plugins(module_names: list[str]) -> list[str]:
    """Import the given modules so their @register_channel calls run.

    Returns the list of modules successfully imported. Import errors are logged
    and skipped so one bad plugin doesn't stop startup.
    """
    loaded: list[str] = []
    for name in module_names:
        name = name.strip()
        if not name:
            continue
        try:
            importlib.import_module(name)
            loaded.append(name)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("failed to load plugin module %s: %s", name, exc)
    return loaded
