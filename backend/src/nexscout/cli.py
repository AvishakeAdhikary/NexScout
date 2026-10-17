"""Command-line entry points: `nexscout serve`, `nexscout migrate`."""

from __future__ import annotations

import argparse
import sys

from nexscout.config import get_settings


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
    )


def _migrate(args: argparse.Namespace) -> None:
    from alembic import command

    from nexscout.infrastructure.db.migrations import alembic_config, setup_checkpointer

    url = get_settings().migration_database_url.get_secret_value()
    command.upgrade(alembic_config(url), args.revision)
    _run(setup_checkpointer(url))


def _run(coro: object) -> None:
    import asyncio

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
        import asyncio

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

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
