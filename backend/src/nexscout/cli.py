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

    from nexscout.infrastructure.db.migrations import alembic_config

    url = get_settings().migration_database_url.get_secret_value()
    command.upgrade(alembic_config(url), args.revision)


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

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
