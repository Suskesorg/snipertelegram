#!/usr/bin/env python3
"""Pemeriksaan tahap M1.

Jalankan:  python3 scripts/m1_check.py

Yang dilakukan:
  1. Membaca file .env dan memeriksa semua isinya.
  2. Mencetak ringkasan konfigurasi (rahasia tidak ikut tercetak).
  3. Membuat / membuka database dan menampilkan daftar tabelnya.
  4. Menulis satu baris log percobaan, termasuk uji sensor private key.

Kalau ada yang salah, skrip ini berhenti dan memberi tahu baris mana di
file .env yang harus diperbaiki.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Supaya skrip bisa dijalankan langsung dari folder proyek.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sniper.config import ConfigError, load_config  # noqa: E402
from sniper.db import open_database  # noqa: E402
from sniper.logging_setup import setup_logging, tx_link  # noqa: E402


def main() -> int:
    print("=" * 62)
    print(" PEMERIKSAAN TAHAP M1")
    print("=" * 62)

    # --- 1. konfigurasi ---
    try:
        cfg = load_config()
    except ConfigError as exc:
        print("\n[GAGAL] Konfigurasi belum benar:\n")
        print("  " + str(exc).replace("\n", "\n  "))
        print("\nPerbaiki file .env lalu jalankan lagi perintah ini.")
        return 1

    log = setup_logging(cfg.log_dir, cfg.log_level)

    print("\n-- Konfigurasi terbaca --")
    for line in cfg.summary_lines():
        print("  " + line)

    if cfg.dry_run:
        print("\n  >> Mode simulasi aktif. Tidak ada uang yang bisa keluar. <<")
    else:
        print("\n  >> PERINGATAN: DRY_RUN=false. Mode uang sungguhan. <<")

    if not cfg.daily_loss_limit_enabled:
        print("\n  >> Rem rugi harian TIDAK AKTIF (MAX_DAILY_LOSS_BNB=0).")
        print(f"     Satu-satunya pembatas yang tersisa adalah "
              f"MAX_OPEN_POSITIONS={cfg.max_open_positions},")
        print(f"     yaitu maksimal {cfg.max_open_positions * cfg.buy_amount_bnb} BNB "
              f"berisiko pada satu waktu. <<")

    # --- 2. database ---
    print("\n-- Database --")
    db = open_database(cfg.database_path)
    print(f"  File     : {cfg.database_path}")
    print(f"  Tabel    : {', '.join(db.table_names())}")

    db.ensure_today_row(cfg.dry_run)
    db.set_state("m1_check_ok", "true")
    print(f"  Tulis/baca uji : bot_state.m1_check_ok = {db.get_state('m1_check_ok')}")
    print(f"  Posisi terbuka       : {db.count_open_positions(cfg.dry_run)}")
    print(f"  - modal masih di dalam : {db.count_at_risk_positions(cfg.dry_run)}"
          f"  (batasnya {cfg.max_open_positions})")
    print(f"  - sudah bebas risiko   : {db.count_riskfree_positions(cfg.dry_run)}"
          f"  (tidak memakan kuota)")
    print(f"  Bot dijeda     : {'ya' if db.is_paused() else 'tidak'}")

    # --- 3. logging + uji sensor ---
    print("\n-- Log --")
    log.info("Pemeriksaan M1 berjalan. Mode dry_run=%s", cfg.dry_run)

    fake_key = "0x" + "ab" * 32
    fake_tx_link = tx_link("0x" + "cd" * 32)
    log.info("Uji sensor, kunci palsu berikut harus tersensor: %s", fake_key)
    log.info("Uji hash transaksi, link berikut harus tampil utuh: %s", fake_tx_link)

    log_file = cfg.log_dir / "sniper.log"
    text = log_file.read_text(encoding="utf-8")
    if fake_key in text or ("ab" * 32) in text:
        print("  [GAGAL] Private key palsu BOCOR ke file log. Jangan lanjut.")
        return 1
    if fake_tx_link not in text:
        print("  [GAGAL] Link transaksi ikut tersensor. Log jadi tidak berguna.")
        return 1
    print(f"  File log : {log_file}")
    print("  Sensor private key : BERHASIL (kunci palsu tidak ada di file log)")
    print("  Link transaksi     : BERHASIL (tetap utuh, bisa dibuka di BscScan)")

    db.close()
    print("\n" + "=" * 62)
    print(" M1 SELESAI. Semua bagian dasar berjalan.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
