"""Pengaturan logging.

Aturan keras: private key TIDAK BOLEH pernah muncul di log.

Cara kerja sensor (dua lapis):
  Lapis 1 - nilai rahasia yang didaftarkan lewat `register_secret()` (isi
            PRIVATE_KEY, token bot, api hash) disensor persis, dalam bentuk
            dengan maupun tanpa awalan "0x".
  Lapis 2 - jaring pengaman: APA PUN yang berbentuk 64 karakter hex ikut
            disensor, dengan atau tanpa awalan "0x".

Satu-satunya pengecualian: teks yang berbentuk link transaksi BscScan
(https://bscscan.com/tx/0x...) dibiarkan utuh, supaya Anda tetap bisa
membuka transaksi bot di BscScan. Karena itu hash transaksi HARUS selalu
ditulis lewat helper `tx_link()` di bawah, tidak pernah telanjang.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

# Jaring pengaman: 64 hex, dengan atau tanpa awalan "0x".
_ANY_64_HEX = re.compile(r"(?<![0-9a-fA-F])(?:0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])")

# Satu-satunya bentuk yang dikecualikan: link transaksi BscScan.
_TX_URL = re.compile(r"https://bscscan\.com/tx/0x[0-9a-fA-F]{64}\b")

# Penanda sementara saat menyelamatkan link transaksi dari sensor.
_KEEP_MARK = "\x00KEEP{}\x00"

# Nilai rahasia yang didaftarkan saat runtime.
_REGISTERED_SECRETS: set[str] = set()

REDACTED = "[DISENSOR]"


def register_secret(value: str | None) -> None:
    """Daftarkan sebuah nilai rahasia supaya selalu disensor dari log.

    Varian dengan dan tanpa awalan "0x" ikut didaftarkan.
    """
    if not value:
        return
    value = value.strip()
    if len(value) < 8:
        return
    _REGISTERED_SECRETS.add(value)
    if value.startswith("0x") or value.startswith("0X"):
        _REGISTERED_SECRETS.add(value[2:])
    else:
        _REGISTERED_SECRETS.add("0x" + value)


def scrub(text: str) -> str:
    """Buang semua rahasia dari sebuah teks.

    Urutan kerjanya penting:
      1. Rahasia terdaftar disensor lebih dulu. Kalau private key kebetulan
         ditulis dalam bentuk link BscScan palsu, tetap kena di langkah ini.
      2. Link transaksi BscScan yang tersisa "dititipkan" sementara.
      3. Semua sisa 64-hex disensor.
      4. Link transaksi dikembalikan utuh.
    """
    for secret in _REGISTERED_SECRETS:
        if secret in text:
            text = text.replace(secret, REDACTED)

    kept: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return _KEEP_MARK.format(len(kept) - 1)

    text = _TX_URL.sub(_stash, text)
    text = _ANY_64_HEX.sub(REDACTED, text)
    for index, original in enumerate(kept):
        text = text.replace(_KEEP_MARK.format(index), original)
    return text


class SecretsFilter(logging.Filter):
    """Menyensor rahasia dari setiap baris log sebelum ditulis."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # argumen log rusak, biarkan lewat apa adanya
            return True
        cleaned = scrub(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def tx_link(tx_hash: str) -> str:
    """Tulis hash transaksi sebagai link BscScan yang bisa langsung diklik."""
    h = tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash
    return f"https://bscscan.com/tx/{h}"


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """Siapkan logging ke layar + file yang berputar otomatis.

    File log: <log_dir>/sniper.log (maks 10 MB, disimpan 7 file lama).
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Bersihkan handler lama supaya tidak dobel kalau fungsi dipanggil ulang.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    secrets_filter = SecretsFilter()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(secrets_filter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "sniper.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(secrets_filter)
    root.addHandler(file_handler)

    # Paket pihak ketiga terlalu berisik.
    for noisy in ("telethon", "web3", "urllib3", "httpx", "asyncio", "aiohttp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger("sniper")
