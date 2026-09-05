#!/usr/bin/env python3
"""Cek jaringan + verifikasi alamat kontrak langsung ke blockchain.

Jalankan:  python3 scripts/cek_jaringan.py

Yang dilakukan:
  1. Menyambung ke RPC_READ_URL, memastikan chain id-nya 56.
  2. Melaporkan gas price yang SEDANG BERLAKU, supaya Anda bisa memilih
     angka MAX_GAS_PRICE_GWEI berdasarkan kenyataan, bukan tebakan.
  3. Memverifikasi alamat kontrak di .env langsung ke blockchain:
       - alamat itu benar-benar berisi kode kontrak
       - router.factory() harus sama dengan PANCAKE_FACTORY_ADDRESS
       - router.WETH()    harus sama dengan WBNB_ADDRESS
       - WBNB harus bernama WBNB dan berdesimal 18
     Ini pembuktian dari blockchain itu sendiri, bukan dari daftar alamat
     yang bisa saja salah salin.
  4. Menguji RPC_PRIVATE_URL apakah hidup dan chain id-nya juga 56.

Skrip ini HANYA MEMBACA. Tidak mengirim transaksi, tidak butuh private key.
"""
from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web3 import Web3  # noqa: E402

from sniper.config import ConfigError, load_config  # noqa: E402

ROUTER_ABI = [
    {"inputs": [], "name": "factory",
     "outputs": [{"internalType": "address", "name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "WETH",
     "outputs": [{"internalType": "address", "name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
]

ERC20_ABI = [
    {"inputs": [], "name": "symbol",
     "outputs": [{"internalType": "string", "name": "", "type": "string"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals",
     "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
     "stateMutability": "view", "type": "function"},
]

OK = "  [OK]   "
BAD = "  [SALAH]"


def main() -> int:
    print("=" * 62)
    print(" CEK JARINGAN & VERIFIKASI ALAMAT KONTRAK")
    print("=" * 62)

    try:
        cfg = load_config()
    except ConfigError as exc:
        print("\n[GAGAL] Konfigurasi belum benar:\n")
        print("  " + str(exc).replace("\n", "\n  "))
        return 1

    problems = 0

    # ---- 1. sambungan RPC baca ----
    print(f"\n-- Sambungan ke RPC baca --\n   {cfg.rpc_read_url}")
    w3 = Web3(Web3.HTTPProvider(cfg.rpc_read_url, request_kwargs={"timeout": 15}))
    try:
        started = time.perf_counter()
        chain_id = w3.eth.chain_id
        latency_ms = (time.perf_counter() - started) * 1000
    except Exception as exc:
        print(f"{BAD} Tidak bisa menyambung: {type(exc).__name__}: {exc}")
        print("\n   Periksa RPC_READ_URL di .env, atau koneksi internet VPS Anda.")
        return 1

    if chain_id == 56:
        print(f"{OK} Chain id 56 (BNB Smart Chain), balasan {latency_ms:.0f} ms")
    else:
        print(f"{BAD} Chain id {chain_id}, seharusnya 56. RPC ini bukan BSC.")
        problems += 1

    block = w3.eth.block_number
    print(f"{OK} Blok terakhir: {block:,}")

    # ---- 2. gas price sekarang ----
    print("\n-- Gas price yang sedang berlaku --")
    gas_wei = w3.eth.gas_price
    gas_gwei = Decimal(gas_wei) / Decimal(10) ** 9
    print(f"{OK} Sekarang: {gas_gwei:.3f} gwei")
    print(f"         Batas Anda di .env (MAX_GAS_PRICE_GWEI): {cfg.max_gas_price_gwei} gwei")
    if cfg.max_gas_price_gwei < gas_gwei:
        print(f"{BAD} Batas Anda LEBIH RENDAH dari gas saat ini. Semua transaksi")
        print("         akan ditolak sendiri oleh bot. Naikkan MAX_GAS_PRICE_GWEI.")
        problems += 1
    else:
        kelipatan = cfg.max_gas_price_gwei / gas_gwei if gas_gwei > 0 else Decimal(0)
        print(f"{OK} Batas Anda = {kelipatan:.1f}x gas saat ini. "
              f"Itu ruang untuk menaikkan gas saat percobaan ulang.")

    # perkiraan ongkos satu penjualan, pakai gas yang berlaku sekarang
    perkiraan_gas_unit = 400_000  # swap dengan token berpajak, angka kasar
    ongkos = Decimal(gas_wei) * perkiraan_gas_unit / Decimal(10) ** 18
    print(f"         Perkiraan ongkos 1x jual (~{perkiraan_gas_unit:,} gas): {ongkos:.6f} BNB")
    if cfg.gas_reserve_bnb > 0 and ongkos > 0:
        print(f"         Cadangan gas {cfg.gas_reserve_bnb} BNB cukup untuk "
              f"kira-kira {int(cfg.gas_reserve_bnb / ongkos)} kali jual.")

    # ---- 3. verifikasi kontrak ----
    print("\n-- Verifikasi alamat kontrak langsung ke blockchain --")

    for nama, alamat in (("Router", cfg.router_address),
                         ("Factory", cfg.factory_address),
                         ("WBNB", cfg.wbnb_address)):
        code = w3.eth.get_code(alamat)
        if len(code) > 2:
            print(f"{OK} {nama:8s} {alamat} berisi kode kontrak ({len(code):,} byte)")
        else:
            print(f"{BAD} {nama:8s} {alamat} KOSONG, tidak ada kontrak di situ.")
            problems += 1

    router = w3.eth.contract(address=cfg.router_address, abi=ROUTER_ABI)
    try:
        factory_dari_router = router.functions.factory().call()
        weth_dari_router = router.functions.WETH().call()
    except Exception as exc:
        print(f"{BAD} Alamat router tidak berperilaku seperti router PancakeSwap: {exc}")
        return 1

    if factory_dari_router == cfg.factory_address:
        print(f"{OK} router.factory() cocok dengan PANCAKE_FACTORY_ADDRESS")
    else:
        print(f"{BAD} router.factory() = {factory_dari_router}")
        print(f"         tapi .env berisi  {cfg.factory_address}")
        problems += 1

    if weth_dari_router == cfg.wbnb_address:
        print(f"{OK} router.WETH() cocok dengan WBNB_ADDRESS")
    else:
        print(f"{BAD} router.WETH()   = {weth_dari_router}")
        print(f"         tapi .env berisi  {cfg.wbnb_address}")
        problems += 1

    wbnb = w3.eth.contract(address=cfg.wbnb_address, abi=ERC20_ABI)
    try:
        symbol = wbnb.functions.symbol().call()
        decimals = wbnb.functions.decimals().call()
        if symbol == "WBNB" and decimals == 18:
            print(f"{OK} WBNB bernama '{symbol}' dengan {decimals} desimal")
        else:
            print(f"{BAD} Token di WBNB_ADDRESS bernama '{symbol}' "
                  f"dengan {decimals} desimal. Bukan WBNB.")
            problems += 1
    except Exception as exc:
        print(f"{BAD} Tidak bisa membaca token WBNB: {exc}")
        problems += 1

    # ---- 4. RPC privat ----
    print(f"\n-- Sambungan ke RPC privat (pengirim transaksi) --\n   {cfg.rpc_private_url}")
    w3p = Web3(Web3.HTTPProvider(cfg.rpc_private_url, request_kwargs={"timeout": 15}))
    try:
        started = time.perf_counter()
        chain_id_p = w3p.eth.chain_id
        latency_p = (time.perf_counter() - started) * 1000
        if chain_id_p == 56:
            print(f"{OK} Hidup, chain id 56, balasan {latency_p:.0f} ms")
        else:
            print(f"{BAD} Chain id {chain_id_p}, seharusnya 56.")
            problems += 1
    except Exception as exc:
        print(f"{BAD} Tidak bisa menyambung: {type(exc).__name__}: {exc}")
        print("         RPC privat sering menolak permintaan baca biasa.")
        print("         Kalau begitu, tidak apa-apa: yang penting nanti dia mau")
        print("         menerima kiriman transaksi. Kita uji lagi di tahap M3.")

    # ---- ringkasan ----
    print("\n" + "=" * 62)
    if problems == 0:
        print(" SEMUA COCOK. Alamat kontrak terbukti benar dari blockchain.")
    else:
        print(f" ADA {problems} MASALAH DI ATAS. Perbaiki dulu sebelum lanjut.")
    print("=" * 62)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
