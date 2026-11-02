"""Database engine and session management (synchronous SQLAlchemy 2.0).

Sync sessions are used deliberately: FastAPI runs sync path operations in a
threadpool, and background async tasks (poller, alert engine) touch the DB via
``asyncio.to_thread``. This keeps transactions short and avoids the sharp edges
of async SQLite while remaining fully compatible with PostgreSQL/TimescaleDB.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _make_engine():
    connect_args: dict = {}
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if settings.is_sqlite:
        # check_same_thread=False lets the poller thread reuse the connection.
        connect_args["check_same_thread"] = False
        # A single shared connection avoids "database is locked" churn under the
        # light write load of the simulator while keeping SQLite single-file.
        from sqlalchemy.pool import StaticPool

        if ":memory:" in settings.database_url:
            kwargs["poolclass"] = StaticPool
    return create_engine(settings.database_url, connect_args=connect_args, **kwargs)


engine = _make_engine()

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background tasks and scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Production uses migrations; MVP uses create_all."""
    from . import models  # register mappers (import for its side effects)

    _ = models  # bare pyflakes ignores "# noqa"; touch the name so it counts as used

    if settings.is_sqlite:
        # Enforce foreign keys on SQLite.
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_con, _):  # pragma: no cover - trivial
            cur = dbapi_con.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _reparar_oids_de_plantilla()


def _reparar_oids_de_plantilla() -> None:
    """Corrige los catálogos creados con las plantillas malas de antes de 1.2.1.

    Las plantillas de Dell, HPE y APC llevaban OID que no se habían comprobado
    contra el MIB del fabricante: las de HPE no devolvían nada por faltarles un
    componente del índice, la de APC apuntaba a otra rama, y las lecturas en
    décimas se guardaban sin dividir (275 en vez de 27,5 °C). Arreglar la
    plantilla no ayuda a quien ya creó el dispositivo, así que hay que tocar lo
    que está guardado.

    Solo se corrigen filas cuya escala sigue a NULL, que es justo lo que
    identifica a una fila anterior a este cambio. Eso deja intacto cualquier
    ajuste hecho a mano y hace que repetirlo no tenga efecto.
    """
    import logging

    from sqlalchemy import inspect as _inspect
    from sqlalchemy import text as _text

    from .services.templates import LEGACY_OID_FIXES

    log = logging.getLogger("rackmon.db")
    try:
        insp = _inspect(engine)
        if "metrics_catalog" not in set(insp.get_table_names()):
            return
        if "scale" not in {c["name"] for c in insp.get_columns("metrics_catalog")}:
            return  # la columna aún no existe: nada que reparar
    except Exception:  # pragma: no cover - inspection failure is non-fatal
        return

    from datetime import datetime, timezone

    ahora = datetime.now(timezone.utc)
    arregladas = 0
    try:
        with engine.begin() as conn:
            for (nombre, oid_viejo), (oid_bueno, escala) in LEGACY_OID_FIXES.items():
                # Primero se mira a QUIÉN afecta, porque después del UPDATE ya no
                # hay forma de saberlo, y hace falta para dejar constancia.
                afectadas = conn.execute(
                    _text(
                        "SELECT id, device_id FROM metrics_catalog "
                        "WHERE name = :nombre AND oid = :viejo AND scale IS NULL"
                    ),
                    {"nombre": nombre, "viejo": oid_viejo},
                ).fetchall()
                if not afectadas:
                    continue

                conn.execute(
                    _text(
                        "UPDATE metrics_catalog SET oid = :nuevo, scale = :escala "
                        "WHERE name = :nombre AND oid = :viejo AND scale IS NULL"
                    ),
                    {"nuevo": oid_bueno, "escala": escala, "nombre": nombre, "viejo": oid_viejo},
                )
                arregladas += len(afectadas)

                # Una nota en la línea de tiempo del equipo, justo donde se
                # produce el escalón. Sin esto, el histórico anterior y el nuevo
                # conviven en la misma gráfica sin que nadie sepa por qué el
                # valor cayó de 275 a 27,5 — y una regla de alerta ajustada a
                # mano sobre los números viejos deja de dispararse en silencio.
                cambio = []
                if oid_bueno != oid_viejo:
                    cambio.append("se estaba leyendo el OID equivocado")
                if escala != 1.0:
                    cambio.append(f"y la lectura necesitaba escalarse (x{escala:g})")
                texto = (
                    f"RackMon corrigió la métrica «{nombre}» al actualizar: "
                    + " ".join(cambio)
                    + ". Los datos anteriores a este punto no son comparables con los "
                    "posteriores. Si tenías una regla de alerta ajustada a los valores "
                    "antiguos, revísala."
                )
                for fila in afectadas:
                    conn.execute(
                        _text(
                            "INSERT INTO annotations (device_id, metric, text, at, created_at) "
                            "VALUES (:dev, :metric, :texto, :cuando, :cuando)"
                        ),
                        {"dev": fila[1], "metric": nombre, "texto": texto, "cuando": ahora},
                    )
    except Exception as exc:  # pragma: no cover - best effort, never block boot
        log.warning("no he podido reparar los OID de plantilla (%s)", exc)
        return

    if arregladas:
        log.warning(
            "repaired %d metric(s) created from a pre-1.2.1 vendor template: the OIDs were "
            "wrong (missing index component, wrong subtree) or the reading needed scaling",
            arregladas,
        )


def _ensure_columns() -> None:
    """Additive, idempotent safety net for schema upgrades.

    ``create_all`` never alters existing tables, so a new version that adds a
    column would leave old deployments with a stale table (and 500s on any query
    touching the new column). This adds columns that exist in the models but are
    missing from existing tables. It only *adds* nullable-compatible columns —
    it never drops or retypes, so type changes and drops still need a real
    migration. Safe to run on every startup.
    """
    import logging

    from sqlalchemy import inspect as _inspect
    from sqlalchemy import text as _text

    log = logging.getLogger("rackmon.db")
    insp = _inspect(engine)
    try:
        existing_tables = set(insp.get_table_names())
    except Exception:  # pragma: no cover - inspection failure is non-fatal
        return
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            db_cols = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in db_cols:
                    continue
                try:
                    coltype = col.type.compile(dialect=engine.dialect)
                    conn.execute(_text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))
                    log.warning("schema upgrade: added missing column %s.%s", table.name, col.name)
                except Exception as exc:  # pragma: no cover - best effort
                    log.warning("schema upgrade: could not add %s.%s (%s)", table.name, col.name, exc)
