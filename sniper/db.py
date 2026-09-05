"""Database SQLite: catatan call, posisi, transaksi, dan statistik harian.

Catatan penting soal angka:
    Jumlah token dan jumlah BNB disimpan dalam satuan terkecil ("wei").
    Angka ini bisa sangat besar, misal 1.000.000.000 token berdesimal 18
    = 1000000000000000000000000000, yang MELEBIHI batas angka bulat SQLite.
    Karena itu semua jumlah disimpan sebagai TEKS, lalu diubah kembali ke
    angka dengan int() saat dibaca. Jangan pernah menyimpannya sebagai INTEGER.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
-- Versi skema, dipakai untuk migrasi di kemudian hari.
CREATE TABLE IF NOT EXISTS schema_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Setiap token yang pernah kita lihat. Dipakai untuk dedupe:
-- satu token tidak dibeli dua kali.
CREATE TABLE IF NOT EXISTS token_registry (
    token_address  TEXT PRIMARY KEY,
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    times_called   INTEGER NOT NULL DEFAULT 1,
    ever_bought    INTEGER NOT NULL DEFAULT 0,
    symbol         TEXT,
    decimals       INTEGER
);

-- Setiap pesan channel yang mengandung alamat kontrak.
CREATE TABLE IF NOT EXISTS calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address  TEXT NOT NULL,
    chat_id        INTEGER NOT NULL,
    chat_title     TEXT,
    message_id     INTEGER NOT NULL,
    message_text   TEXT,
    detected_at    TEXT NOT NULL,
    -- new | duplicate | blacklisted | skipped | buying | bought | failed
    status         TEXT NOT NULL DEFAULT 'new',
    skip_reason    TEXT,
    position_id    INTEGER,
    UNIQUE (chat_id, message_id, token_address)
);
CREATE INDEX IF NOT EXISTS idx_calls_token  ON calls (token_address);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls (status);

-- Posisi token yang kita pegang.
CREATE TABLE IF NOT EXISTS positions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id                  INTEGER,
    token_address            TEXT NOT NULL,
    token_symbol             TEXT,
    token_decimals           INTEGER,
    -- 1 = posisi hasil simulasi, 0 = posisi uang sungguhan. Jangan dicampur.
    dry_run                  INTEGER NOT NULL,
    -- open | closed | failed
    status                   TEXT NOT NULL DEFAULT 'open',
    buy_tx_hash              TEXT,
    approve_tx_hash          TEXT,
    bnb_invested_wei         TEXT NOT NULL DEFAULT '0',
    tokens_bought_wei        TEXT NOT NULL DEFAULT '0',
    tokens_remaining_wei     TEXT NOT NULL DEFAULT '0',
    bnb_returned_wei         TEXT NOT NULL DEFAULT '0',
    gas_spent_wei            TEXT NOT NULL DEFAULT '0',
    -- harga dalam wei BNB untuk 1 satuan terkecil token
    entry_price_wei          TEXT,
    peak_price_wei           TEXT,
    last_price_wei           TEXT,
    last_price_at            TEXT,
    principal_recovered      INTEGER NOT NULL DEFAULT 0,
    principal_recovered_at   TEXT,
    opened_at                TEXT NOT NULL,
    closed_at                TEXT,
    close_reason             TEXT,
    notes                    TEXT,
    FOREIGN KEY (call_id) REFERENCES calls (id)
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status, dry_run, principal_recovered);
CREATE INDEX IF NOT EXISTS idx_positions_token  ON positions (token_address);

-- Setiap percobaan transaksi, termasuk percobaan ulang dengan gas lebih tinggi.
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     INTEGER,
    -- buy | sell | approve
    side            TEXT NOT NULL,
    -- initial_buy | approve | principal | trailing_stop | manual | panic
    reason          TEXT NOT NULL,
    -- pending | confirmed | failed | abandoned
    status          TEXT NOT NULL DEFAULT 'pending',
    dry_run         INTEGER NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    tx_hash         TEXT,
    nonce           INTEGER,
    bnb_wei         TEXT,
    token_wei       TEXT,
    gas_price_wei   TEXT,
    gas_limit       INTEGER,
    gas_used        INTEGER,
    created_at      TEXT NOT NULL,
    confirmed_at    TEXT,
    error           TEXT,
    FOREIGN KEY (position_id) REFERENCES positions (id)
);
CREATE INDEX IF NOT EXISTS idx_trades_position ON trades (position_id);
CREATE INDEX IF NOT EXISTS idx_trades_status   ON trades (status);

-- Statistik per hari, dipakai untuk batas rugi harian.
CREATE TABLE IF NOT EXISTS daily_stats (
    day               TEXT NOT NULL,
    dry_run           INTEGER NOT NULL,
    spent_wei         TEXT NOT NULL DEFAULT '0',
    returned_wei      TEXT NOT NULL DEFAULT '0',
    gas_wei           TEXT NOT NULL DEFAULT '0',
    realized_pnl_wei  TEXT NOT NULL DEFAULT '0',
    buys              INTEGER NOT NULL DEFAULT 0,
    sells             INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, dry_run)
);

-- Keadaan bot yang harus bertahan setelah restart, mis. pause/resume.
CREATE TABLE IF NOT EXISTS bot_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    """Waktu sekarang dalam format ISO UTC, dipakai di semua kolom waktu."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Database:
    """Pembungkus SQLite yang aman dipakai dari banyak task sekaligus."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=FULL")

    # -- dasar ------------------------------------------------------------
    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute(
                "INSERT INTO schema_info (key, value) VALUES ('version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def table_names(self) -> list[str]:
        rows = self.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r["name"] for r in rows]

    # -- keadaan bot ------------------------------------------------------
    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM bot_state WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value, utcnow()),
        )

    def is_paused(self) -> bool:
        return self.get_state("paused", "false") == "true"

    def set_paused(self, paused: bool) -> None:
        self.set_state("paused", "true" if paused else "false")

    # -- token & dedupe ---------------------------------------------------
    def seen_before(self, token_address: str) -> bool:
        """True kalau token ini sudah pernah tercatat sebelumnya."""
        return self.query_one(
            "SELECT 1 FROM token_registry WHERE token_address = ?", (token_address,)
        ) is not None

    def ever_bought(self, token_address: str) -> bool:
        row = self.query_one(
            "SELECT ever_bought FROM token_registry WHERE token_address = ?",
            (token_address,),
        )
        return bool(row["ever_bought"]) if row else False

    def register_token(self, token_address: str) -> bool:
        """Catat token. Kembalikan True kalau ini kemunculan PERTAMA."""
        now = utcnow()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO token_registry (token_address, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?) ON CONFLICT(token_address) DO UPDATE SET "
                "last_seen_at = excluded.last_seen_at, times_called = times_called + 1",
                (token_address, now, now),
            )
            self._conn.commit()
            # rowcount 1 pada INSERT baru, juga 1 pada UPDATE; pakai times_called.
            row = self._conn.execute(
                "SELECT times_called FROM token_registry WHERE token_address = ?",
                (token_address,),
            ).fetchone()
            return row["times_called"] == 1

    def mark_bought(self, token_address: str) -> None:
        self.execute(
            "UPDATE token_registry SET ever_bought = 1 WHERE token_address = ?",
            (token_address,),
        )

    # -- posisi -----------------------------------------------------------
    def open_positions(self, dry_run: bool) -> list[sqlite3.Row]:
        return self.query_all(
            "SELECT * FROM positions WHERE status = 'open' AND dry_run = ? "
            "ORDER BY id",
            (1 if dry_run else 0,),
        )

    def count_open_positions(self, dry_run: bool) -> int:
        """Semua posisi terbuka, termasuk yang modalnya sudah ditarik."""
        row = self.query_one(
            "SELECT COUNT(*) AS n FROM positions WHERE status = 'open' AND dry_run = ?",
            (1 if dry_run else 0,),
        )
        return int(row["n"]) if row else 0

    def at_risk_positions(self, dry_run: bool) -> list[sqlite3.Row]:
        """Posisi yang modal awalnya MASIH di dalam (belum ditarik)."""
        return self.query_all(
            "SELECT * FROM positions WHERE status = 'open' AND dry_run = ? "
            "AND principal_recovered = 0 ORDER BY id",
            (1 if dry_run else 0,),
        )

    def count_at_risk_positions(self, dry_run: bool) -> int:
        """Angka inilah yang dibandingkan dengan MAX_OPEN_POSITIONS.

        Posisi yang modal awalnya sudah ditarik (principal_recovered = 1)
        sudah bebas risiko, jadi TIDAK memakan kuota. Batasnya berarti
        "maksimal sekian posisi yang uang modalnya masih terpasang".
        """
        row = self.query_one(
            "SELECT COUNT(*) AS n FROM positions WHERE status = 'open' "
            "AND dry_run = ? AND principal_recovered = 0",
            (1 if dry_run else 0,),
        )
        return int(row["n"]) if row else 0

    def count_riskfree_positions(self, dry_run: bool) -> int:
        """Posisi terbuka yang modalnya sudah kembali. Tidak memakan kuota."""
        row = self.query_one(
            "SELECT COUNT(*) AS n FROM positions WHERE status = 'open' "
            "AND dry_run = ? AND principal_recovered = 1",
            (1 if dry_run else 0,),
        )
        return int(row["n"]) if row else 0

    # -- statistik harian -------------------------------------------------
    def ensure_today_row(self, dry_run: bool) -> None:
        self.execute(
            "INSERT OR IGNORE INTO daily_stats (day, dry_run) VALUES (?, ?)",
            (today_utc(), 1 if dry_run else 0),
        )

    def today_realized_pnl_wei(self, dry_run: bool) -> int:
        row = self.query_one(
            "SELECT realized_pnl_wei FROM daily_stats WHERE day = ? AND dry_run = ?",
            (today_utc(), 1 if dry_run else 0),
        )
        return int(row["realized_pnl_wei"]) if row else 0


def open_database(path: Path) -> Database:
    db = Database(path)
    db.init_schema()
    return db
