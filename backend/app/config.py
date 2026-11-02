"""Central configuration.

All settings are read from environment variables (prefix ``RACKMON_``) or an
``.env`` file, with sensible defaults that let the stack boot locally with zero
configuration. Production deployments override the security-sensitive values.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.3.0"

# Insecure development defaults. These let the stack boot with zero config, but
# the app refuses to start in production while any of them is still in use (see
# ``production_safety_check``). Kept as named constants so the guard can never
# drift from the actual field defaults.
DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-me-please-0000000000"
DEV_MASTER_KEY = "dev-insecure-master-key-change-me-please"
DEV_ADMIN_PASSWORD = "admin12345"
# La contraseña de la cuenta de solo lectura. Está PUBLICADA en rackmon.app como
# el acceso de la demo, así que fuera de un portátil no es una contraseña: es una
# puerta abierta que cualquiera puede leer en la web. Se trata aparte del resto
# (ver `seed_all`): la cuenta no se crea con ella en una instalación normal, y si
# ya existe se desactiva al arrancar.
DEV_VIEWER_PASSWORD = "viewer12345"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RACKMON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # La referencia interactiva de la API (/docs, /redoc, /openapi.json).
    # Cerrada salvo que se pida expresamente, y NO atada a `environment`.
    # El motivo: `environment` vale "development" por defecto, así que una
    # instalación que simplemente se olvide de ponerlo en "production" queda con
    # el mapa completo de la API —todas las rutas, parámetros y esquemas— abierto
    # sin necesidad de cuenta. Un despiste en la configuración no debería abrir
    # nada. Quien la necesite para desarrollar, la enciende:
    # RACKMON_API_DOCS_ENABLED=true.
    api_docs_enabled: bool = False

    # Optional bearer token guarding GET /metrics (Prometheus scrape). When
    # empty, /metrics still requires a normal authenticated principal (JWT or
    # API key) — it is never exposed unauthenticated.
    metrics_token: str = ""

    # --- Database ---
    # Default is a local SQLite file so the app runs with no external services.
    # In production set e.g. postgresql+psycopg2://user:pass@postgres:5432/rackmon
    database_url: str = "sqlite:///./rackmon.db"

    # --- Security ---
    # 32-byte urlsafe key used to sign JWTs. MUST be overridden in production.
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7

    # Master key for AES-256-GCM encryption of secrets at rest (SNMP/SMTP).
    # Provide 32 raw bytes, or any string (it is hashed to 32 bytes).
    # MUST be overridden in production and kept out of the database.
    master_key: str = DEV_MASTER_KEY

    # Password policy
    password_min_length: int = 8
    max_login_attempts: int = 5
    lockout_seconds: int = 300

    # --- CORS (dev: allow the Vite dev server) ---
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # --- Poller ---
    poller_enabled: bool = True
    # Optional Redis pub/sub URL for cross-replica real-time fan-out.
    # Empty = in-process only (single-node). e.g. redis://localhost:6379/0
    redis_url: str = ""
    poller_tick_seconds: float = 3.0          # how often the loop wakes up
    poller_use_simulator: bool = True         # False -> real SNMP via pysnmp
    snmp_timeout_seconds: float = 2.0
    snmp_retries: int = 2

    # --- Retention (raw points) ---
    raw_retention_days: int = 30
    retention_sweep_minutes: int = 60

    # --- Alert escalation ---
    escalation_enabled: bool = False
    escalate_after_seconds: int = 900      # 15 min unacknowledged -> escalate
    escalation_recipients: list[str] = Field(default_factory=list)

    # --- LDAP / Active Directory auth ---
    ldap_enabled: bool = False
    ldap_server_uri: str = ""            # ldap://host:389 or ldaps://host:636
    ldap_bind_dn: str = ""               # service account DN for searching
    ldap_bind_password: str = ""
    ldap_user_base_dn: str = ""          # e.g. ou=people,dc=corp,dc=com
    ldap_user_filter: str = "(uid={username})"
    ldap_email_attr: str = "mail"
    ldap_group_attr: str = "memberOf"
    ldap_admin_group: str = ""           # DN or value that grants admin
    ldap_default_role: str = "viewer"

    # --- Compatibilidad: RACKMON_LICENSE_KEY ---
    # Desde la 1.3.0 TODAS las funciones están incluidas y no hay claves que
    # verificar. El campo se conserva para que una instalación que lo tenga puesto
    # en su .env no falle al arrancar: su valor se lee y se ignora.
    license_key: str = ""

    # --- Update check & vendor announcements (opt-in; privacy-preserving) ---
    # Self-hosted RackMon never phones home by default. When enabled (here or via
    # the admin "updates" setting), the app periodically fetches a small static
    # JSON manifest from the vendor (a plain GET — no telemetry is sent) to learn
    # whether a newer version exists and to show optional vendor announcements.
    update_check_enabled: bool = False
    update_manifest_url: str = ""   # empty -> the vendor default manifest URL

    # --- In-app support ("contact vendor" form; opt-in, user-initiated) ---
    # When a user submits the support form, the instance forwards the message
    # server-side to this vendor endpoint (never telemetry — only on a human
    # click). Self-hosters can point it at their own support desk or clear it.
    support_url: str = "https://rackmon.app/support/messages"
    instance_id: str = ""  # optional label identifying this install in messages

    # --- Plugins ---
    plugins_modules: list[str] = Field(default_factory=list)

    # --- SSO (OpenID Connect) ---
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_authorization_endpoint: str = ""  # derived from issuer if empty
    oidc_token_endpoint: str = ""          # derived from issuer if empty
    oidc_jwks_uri: str = ""                 # derived from issuer if empty; used to verify id-token signatures
    oidc_scopes: str = "openid email profile"
    oidc_default_role: str = "viewer"
    oidc_admin_emails: list[str] = Field(default_factory=list)

    # --- SNMP trap receiver (opt-in; needs port privileges) ---
    snmp_trap_enabled: bool = False
    snmp_trap_port: int = 162
    snmp_trap_community: str = "public"

    # --- Scheduled reports ---
    report_weekly_enabled: bool = False
    report_weekly_recipients: list[str] = Field(default_factory=list)

    # --- Alerting / notifications ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True                 # STARTTLS
    smtp_use_ssl: bool = False                # implicit TLS (port 465)
    smtp_from: str = "rackmon@localhost"
    alert_default_recipients: list[str] = Field(default_factory=list)
    public_base_url: str = "http://localhost:8000"

    # --- Extra notification channels (all optional) ---
    alert_webhook_url: str | None = None        # generic JSON webhook (POST)
    slack_webhook_url: str | None = None        # Slack incoming webhook URL
    teams_webhook_url: str | None = None        # Microsoft Teams incoming webhook URL
    telegram_bot_token: str | None = None       # Telegram bot token
    telegram_chat_id: str | None = None         # Telegram chat/channel id

    # --- Modo demostración (SOLO para la demo pública del vendedor) ---
    # Con esto activo, la pantalla de login deja entrar directamente a la cuenta
    # de solo lectura: quien llega a la demo ve el producto sin teclear nada.
    # Apagado por defecto, así que ninguna instalación de cliente se ve afectada
    # jamás por dejarlo sin tocar. El endpoint que lo sirve SOLO entrega una
    # cuenta de rol "viewer": si la configurada no lo es, se niega.
    demo_mode: bool = False
    demo_user_email: str = ""   # vacío = usa viewer_email

    # --- Seed / demo ---
    seed_demo_data: bool = True
    admin_email: str = "admin@rackmon.io"
    admin_password: str = DEV_ADMIN_PASSWORD
    viewer_email: str = "viewer@rackmon.io"
    viewer_password: str = DEV_VIEWER_PASSWORD

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def insecure_defaults_in_use(self) -> list[str]:
        """Return the names of security-sensitive settings still at their
        insecure development default (empty when all are overridden)."""
        checks = {
            "jwt_secret": DEV_JWT_SECRET,
            "master_key": DEV_MASTER_KEY,
            "admin_password": DEV_ADMIN_PASSWORD,
        }
        return [name for name, dev_value in checks.items() if getattr(self, name) == dev_value]

    def placeholder_secrets_in_use(self) -> list[str]:
        """Secretos que siguen con el texto de relleno de una plantilla.

        Distinto de los valores por defecto de desarrollo: esos existen para que
        el proyecto arranque sin configurar nada en tu portátil, y ahí son
        legítimos. Un "CHANGE-ME…" solo aparece cuando alguien instaló desde una
        plantilla (la de Unraid, por ejemplo) y pulsó Aplicar sin rellenarlos.
        Esa cadena está publicada, así que **cualquiera podría firmar un token de
        administrador** para esa instalación y descifrar las credenciales SNMP
        guardadas. No es legítimo en ningún entorno, ni siquiera en desarrollo.
        """
        sospechosos = ("change-me", "changeme", "replace-me", "tu-clave-aqui")
        # Los valores de desarrollo llevan "change-me" dentro a propósito, y son
        # legítimos en un portátil: los gestiona insecure_defaults_in_use(), que
        # avisa en desarrollo y se niega en producción. Aquí no cuentan.
        de_desarrollo = {DEV_JWT_SECRET, DEV_MASTER_KEY, DEV_ADMIN_PASSWORD}
        encontrados = []
        for name in ("jwt_secret", "master_key", "admin_password"):
            valor = str(getattr(self, name) or "")
            if valor in de_desarrollo:
                continue
            if any(s in valor.lower() for s in sospechosos):
                encontrados.append(name)
        return encontrados


def production_safety_check(settings: Settings) -> None:
    """Refuse to start a production instance that still uses insecure default
    secrets. This is the last line of defence for self-hosted deployments: we
    cannot stop an operator from leaving the defaults, but we can stop the app
    from running insecurely with ``RACKMON_ENVIRONMENT=production``."""
    # Los "CHANGE-ME…" de una plantilla se rechazan SIEMPRE, sea cual sea el
    # entorno. Los valores de desarrollo tienen sentido en un portátil; un texto
    # de relleno publicado en una plantilla no lo tiene en ninguna parte, y dejaba
    # instalaciones enteras con una clave de firma que cualquiera puede leer.
    relleno = settings.placeholder_secrets_in_use()
    if relleno:
        names = ", ".join("RACKMON_" + n.upper() for n in relleno)
        raise RuntimeError(
            f"Refusing to start: these secrets still hold the template placeholder: {names}. "
            "That value is published in the install template, so anyone could sign an admin "
            "token for this instance and decrypt its stored SNMP credentials. "
            "Generate a unique value for each with: openssl rand -hex 32   "
            "(note: changing RACKMON_MASTER_KEY makes previously stored device credentials "
            "unreadable, so re-enter them afterwards)."
        )

    insecure = settings.insecure_defaults_in_use()
    if insecure and settings.environment == "production":
        names = ", ".join("RACKMON_" + n.upper() for n in insecure)
        raise RuntimeError(
            f"Refusing to start in production with insecure default secrets: {names}. "
            "Set each to a strong, unique value before deploying."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
