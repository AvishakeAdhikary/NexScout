"""Command-line entry points: `nexscout serve`, `nexscout migrate`."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import TYPE_CHECKING

from nexscout.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from nexscout.application.actor import Actor


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    # psycopg's async driver can't run on Windows' default ProactorEventLoop.
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    uvicorn.run(
        "nexscout.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop=loop,
        proxy_headers=True,
        log_config=None,
        access_log=False,
        # Keep idle connections open longer than the web proxy's (Node) keep-alive, so the
        # proxy never reuses a socket the API is closing at the same moment (ECONNRESET → a
        # spurious 500 for the user).
        timeout_keep_alive=75,
    )


def _migrate(args: argparse.Namespace) -> None:
    from alembic import command

    from nexscout.infrastructure.db.migrations import alembic_config, setup_checkpointer

    url = get_settings().migration_database_url.get_secret_value()
    command.upgrade(alembic_config(url), args.revision)
    _run(setup_checkpointer(url))


def _run(coro: object) -> None:

    if sys.platform == "win32":
        asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)  # type: ignore[arg-type]
    else:
        asyncio.run(coro)  # type: ignore[arg-type]


def _worker(args: argparse.Namespace) -> None:
    import signal
    import threading

    from nexscout.agent_runtime.worker import Worker
    from nexscout.observability import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    worker = Worker(settings)

    async def main() -> None:

        loop = asyncio.get_running_loop()

        def stop(*_: object) -> None:
            loop.call_soon_threadsafe(worker.request_stop)

        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
                if sig is not None:
                    signal.signal(sig, stop)
        await worker.run_forever()

    _run(main())


def _mcp(args: argparse.Namespace) -> None:
    """Read-only MCP server over stdio. The token comes from NEXSCOUT_MCP_TOKEN (never argv,
    which other local users could read from the process list)."""
    import os

    from nexscout.application.tokens import authenticate_token
    from nexscout.domain.errors import AuthenticationFailed
    from nexscout.infrastructure.db.engine import build_engine, build_sessionmaker
    from nexscout.mcp_server import build_server

    token = os.environ.get("NEXSCOUT_MCP_TOKEN", "")
    settings = get_settings()

    async def main() -> None:
        engine = build_engine(settings)
        sessions = build_sessionmaker(engine)
        try:
            async with sessions() as s, s.begin():
                try:
                    user_id = await authenticate_token(s, token)
                except AuthenticationFailed:
                    sys.stderr.write(
                        "NexScout MCP: set NEXSCOUT_MCP_TOKEN to a valid personal access token "
                        "(Account > Access tokens).\n"
                    )
                    raise SystemExit(2) from None
            await build_server(sessions, user_id).run_stdio_async()
        finally:
            await engine.dispose()

    _run(main())


async def _as_user(
    email: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], uuid.UUID]:
    """(engine, session factory, user id) for an operator command acting as one user. Their
    rows are reached through the normal tenant binding, so RLS applies as for the user."""
    from sqlalchemy import select

    from nexscout.application.auth import normalize_email
    from nexscout.infrastructure.db.engine import build_engine, build_sessionmaker
    from nexscout.infrastructure.db.models import User

    engine = build_engine(get_settings())
    sessions = build_sessionmaker(engine)
    async with sessions() as s:
        user_id = await s.scalar(select(User.id).where(User.email == normalize_email(email)))
    if user_id is None:
        await engine.dispose()
        sys.stderr.write(f"No account with the email {email}.\n")
        raise SystemExit(2)
    return engine, sessions, user_id


async def _case_id(s: AsyncSession, actor: Actor, name: str | None) -> uuid.UUID:
    from nexscout.application import cases

    every = await cases.list_cases(s, actor)
    rows = [c for c in every if c.name == name] if name else every
    if len(rows) != 1:
        names = ", ".join(repr(c.name) for c in every)
        sys.stderr.write(f"Choose a case with --case. Cases: {names}\n")
        raise SystemExit(2)
    return rows[0].id


def _case_command(args: argparse.Namespace) -> None:
    """Operator tools for one user's case: export-case, import-case, reread-documents."""
    from pathlib import Path

    from nexscout.application import documents, profile_bundle
    from nexscout.application.actor import Actor
    from nexscout.infrastructure.db.engine import bind_tenant
    from nexscout.infrastructure.storage import LocalObjectStore

    settings = get_settings()
    store = LocalObjectStore(settings.storage_dir)
    bundle = Path(args.file).read_bytes() if args.command == "import-case" else b""

    async def main() -> None:
        engine, sessions, user_id = await _as_user(args.email)
        actor = Actor(user_id=user_id, session_id=uuid.uuid4(), request_id="cli")
        try:
            async with sessions() as s, s.begin():
                await bind_tenant(s, user_id)
                if args.command == "import-case":
                    report = await profile_bundle.import_case(
                        s, actor, store, bundle, max_document_bytes=settings.max_upload_bytes
                    )
                    print(f"Imported into {report.case_name!r} ({report.case_id}): {report.counts}")
                    for w in report.warnings:
                        print(f"  note: {w}")
                    return
                case_id = await _case_id(s, actor, args.case)
                if args.command == "export-case":
                    name, data = await profile_bundle.export_case(
                        s, actor, store, case_id, include_documents=not args.no_documents
                    )
                    out = Path(args.out or name)
                    await asyncio.to_thread(out.write_bytes, data)
                    print(f"Exported to {out} ({len(data)} bytes)")
                    return
                for doc in await documents.list_documents(s, actor, case_id):
                    if documents.DocumentPurpose(doc.purpose) in documents.EXTRACT_FROM:
                        result = await documents.reread_document(s, actor, doc.id)
                        print(f"{doc.filename}: {result}")
        finally:
            await engine.dispose()

    _run(main())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nexscout")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_serve)

    migrate = sub.add_parser("migrate", help="Apply database migrations (owner role)")
    migrate.add_argument("revision", nargs="?", default="head")
    migrate.set_defaults(func=_migrate)

    worker = sub.add_parser("worker", help="Run the durable background worker")
    worker.set_defaults(func=_worker)

    mcp = sub.add_parser("mcp", help="Run the read-only MCP server over stdio")
    mcp.set_defaults(func=_mcp)

    export = sub.add_parser("export-case", help="Export one user's case as a .nexscout file")
    export.add_argument("--email", required=True)
    export.add_argument("--case", help="Case name (needed when the user has several)")
    export.add_argument("--out", help="Output file (default: <case>-<date>.nexscout)")
    export.add_argument("--no-documents", action="store_true", help="Leave out original files")
    export.set_defaults(func=_case_command)

    imp = sub.add_parser("import-case", help="Import a .nexscout file as a new case for a user")
    imp.add_argument("--email", required=True)
    imp.add_argument("--file", required=True)
    imp.set_defaults(func=_case_command)

    reread = sub.add_parser(
        "reread-documents",
        help="Read a case's CVs and letters again (only pending, unedited entries change)",
    )
    reread.add_argument("--email", required=True)
    reread.add_argument("--case", help="Case name (needed when the user has several)")
    reread.set_defaults(func=_case_command)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
