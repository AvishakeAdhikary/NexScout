"""SQLite-backed monthly + daily LLM budget ledger.

Schema: ``(provider TEXT, day TEXT, month TEXT, input_tokens INT,
output_tokens INT, cost_usd REAL, calls INT)``. Aggregation is per
(provider, day) and per (provider, month) on the fly.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from ..core.config import budget_db_path, ensure_dirs

# Token-cost estimates (USD per 1k tokens). Conservative defaults; sites that
# need more accuracy can override at call time.
DEFAULT_COSTS: dict[str, tuple[float, float]] = {
    # provider_prefix -> (input_per_1k, output_per_1k)
    "openai": (0.0050, 0.0150),
    "anthropic": (0.0030, 0.0150),
    "gemini": (0.0001, 0.0004),
    "ollama": (0.0, 0.0),
    "lmstudio": (0.0, 0.0),
    "vllm": (0.0, 0.0),
    "llamacpp": (0.0, 0.0),
}


def _prefix(provider: str) -> str:
    return provider.split(":", 1)[0].split("-", 1)[0].lower()


def _today_iso() -> tuple[str, str]:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")


class BudgetLedger:
    """Per-process budget tracker. Thread-safe."""

    def __init__(self, monthly_usd: float, daily_calls: int, db_path: Path | None = None) -> None:
        self.monthly_usd = monthly_usd
        self.daily_calls = daily_calls
        self.db_path = db_path or budget_db_path()
        self._lock = threading.Lock()
        ensure_dirs()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budget (
                  provider TEXT NOT NULL,
                  day TEXT NOT NULL,
                  month TEXT NOT NULL,
                  input_tokens INTEGER DEFAULT 0,
                  output_tokens INTEGER DEFAULT 0,
                  cost_usd REAL DEFAULT 0,
                  calls INTEGER DEFAULT 0,
                  PRIMARY KEY (provider, day)
                )
                """
            )

    def estimate_cost(self, provider: str, in_tokens: int, out_tokens: int) -> float:
        in_per_1k, out_per_1k = DEFAULT_COSTS.get(_prefix(provider), (0.0, 0.0))
        return (in_tokens / 1000.0) * in_per_1k + (out_tokens / 1000.0) * out_per_1k

    def month_spent(self, provider: str | None = None) -> float:
        _, month = _today_iso()
        with self._connect() as conn:
            if provider is None:
                row = conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM budget WHERE month=?", (month,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd),0) FROM budget WHERE month=? AND provider=?",
                    (month, provider),
                ).fetchone()
            return float(row[0] or 0.0)

    def day_calls(self, provider: str | None = None) -> int:
        day, _ = _today_iso()
        with self._connect() as conn:
            if provider is None:
                row = conn.execute("SELECT COALESCE(SUM(calls),0) FROM budget WHERE day=?", (day,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(calls),0) FROM budget WHERE day=? AND provider=?",
                    (day, provider),
                ).fetchone()
            return int(row[0] or 0)

    def allow(self, provider: str, est_tokens: int = 2048) -> bool:
        """Return True if a call with the given token estimate fits the budget."""
        if self.day_calls() >= self.daily_calls:
            return False
        est_cost = self.estimate_cost(provider, est_tokens // 2, est_tokens // 2)
        return self.month_spent() + est_cost <= self.monthly_usd

    def record(self, provider: str, in_tokens: int, out_tokens: int, cost_usd: float | None = None) -> None:
        """Append a usage event to the ledger."""
        day, month = _today_iso()
        cost = cost_usd if cost_usd is not None else self.estimate_cost(provider, in_tokens, out_tokens)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO budget (provider, day, month, input_tokens, output_tokens, cost_usd, calls)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(provider, day) DO UPDATE SET
                  input_tokens = input_tokens + excluded.input_tokens,
                  output_tokens = output_tokens + excluded.output_tokens,
                  cost_usd = cost_usd + excluded.cost_usd,
                  calls = calls + 1
                """,
                (provider, day, month, in_tokens, out_tokens, cost),
            )

    def reset(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM budget")
