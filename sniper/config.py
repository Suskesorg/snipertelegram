"""Membaca dan memeriksa seluruh konfigurasi dari file .env.

Prinsip:
  1. DRY_RUN default TRUE. Kalau baris DRY_RUN hilang dari .env, bot tetap
     masuk mode simulasi. Uang sungguhan hanya jalan kalau Anda menulis
     DRY_RUN=false secara sadar.
  2. Semua angka yang menyangkut uang WAJIB ada di .env. Tidak ada nilai
     karangan di dalam kode. Kalau kosong, bot menolak jalan dan bilang
     baris mana yang harus diisi.
  3. PRIVATE_KEY hanya dibaca dari .env dan tidak pernah dicetak.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from eth_utils import is_hex_address, to_checksum_address

from .logging_setup import register_secret

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# Nilai placeholder di .env.example yang berarti "belum diisi".
_PLACEHOLDERS = {"", "ISI_SENDIRI", "GANTI_INI", "TODO", "XXX"}


class ConfigError(RuntimeError):
    """Konfigurasi salah atau belum lengkap. Pesannya ditujukan ke manusia."""


# --------------------------------------------------------------------------
# Pembaca nilai mentah
# --------------------------------------------------------------------------

def _raw(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip().strip('"').strip("'")
    if value.upper() in _PLACEHOLDERS:
        return None
    return value


def _require_str(name: str, hint: str) -> str:
    value = _raw(name)
    if value is None:
        raise ConfigError(
            f"{name} belum diisi di file .env\n"
            f"    Buka file .env, cari baris {name}=, lalu isi.\n"
            f"    Keterangan: {hint}"
        )
    return value


def _require_decimal(name: str, hint: str, *, minimum: Decimal | None = None,
                     maximum: Decimal | None = None) -> Decimal:
    text = _require_str(name, hint)
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ConfigError(
            f"{name} harus berupa angka, tapi isinya '{text}'.\n"
            f"    Pakai titik untuk desimal, contoh 0.05 (bukan 0,05)."
        ) from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} tidak boleh lebih kecil dari {minimum}. Isinya sekarang {value}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} tidak boleh lebih besar dari {maximum}. Isinya sekarang {value}.")
    return value


def _require_int(name: str, hint: str, *, minimum: int | None = None,
                 maximum: int | None = None) -> int:
    text = _require_str(name, hint)
    try:
        value = int(text)
    except ValueError as exc:
        raise ConfigError(f"{name} harus berupa angka bulat, tapi isinya '{text}'.") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} tidak boleh lebih kecil dari {minimum}. Isinya sekarang {value}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} tidak boleh lebih besar dari {maximum}. Isinya sekarang {value}.")
    return value


def _require_address(name: str, hint: str) -> str:
    text = _require_str(name, hint)
    if not is_hex_address(text):
        raise ConfigError(
            f"{name} bukan alamat kontrak yang sah: '{text}'\n"
            f"    Alamat yang benar diawali 0x lalu 40 karakter hex."
        )
    return to_checksum_address(text)


def _parse_bool(name: str, default: bool) -> bool:
    """Baca nilai true/false. Apa pun yang tidak jelas dianggap AMAN (True)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().strip('"').strip("'").lower()
    if value in {"true", "1", "yes", "y", "on"}:
        return True
    if value in {"false", "0", "no", "n", "off"}:
        return False
    raise ConfigError(
        f"{name} harus true atau false, tapi isinya '{raw}'.\n"
        f"    Tulis persis: {name}=true  atau  {name}=false"
    )


def _parse_chat_ids(name: str, hint: str) -> list[int]:
    text = _raw(name)
    if text is None:
        return []
    result: list[int] = []
    for piece in text.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            result.append(int(piece))
        except ValueError as exc:
            raise ConfigError(
                f"{name} berisi '{piece}' yang bukan angka.\n"
                f"    Keterangan: {hint}"
            ) from exc
    return result


def _parse_address_list(name: str) -> list[str]:
    text = _raw(name)
    if text is None:
        return []
    result: list[str] = []
    for piece in text.replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        if not is_hex_address(piece):
            raise ConfigError(f"{name} berisi alamat tidak sah: '{piece}'")
        result.append(to_checksum_address(piece))
    return result


# --------------------------------------------------------------------------
# Bentuk konfigurasi
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    # --- saklar keselamatan ---
    dry_run: bool

    # --- jaringan ---
    chain_id: int
    rpc_read_url: str
    rpc_private_url: str

    # --- kontrak ---
    router_address: str
    factory_address: str
    wbnb_address: str

    # --- dompet ---
    private_key: str | None
    wallet_address: str | None

    # --- uang: semua wajib diisi manusia ---
    buy_amount_bnb: Decimal
    max_open_positions: int
    max_daily_loss_bnb: Decimal
    max_gas_price_gwei: Decimal
    buy_slippage_percent: Decimal
    sell_slippage_percent: Decimal
    take_profit_multiplier: Decimal
    trailing_stop_percent: Decimal
    gas_reserve_bnb: Decimal

    # --- Telegram: pendengar (userbot) ---
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_session_name: str
    watch_chat_ids: list[int]

    # --- Telegram: kontrol manual (Bot API) ---
    control_bot_token: str | None
    owner_chat_id: int | None

    # --- daftar alamat yang tidak pernah dibeli ---
    blacklist_addresses: list[str]

    # --- teknis ---
    sell_simulation_timeout_ms: int
    log_level: str
    database_path: Path
    log_dir: Path

    # ---- turunan ----
    @property
    def buy_amount_wei(self) -> int:
        return int(self.buy_amount_bnb * Decimal(10) ** 18)

    @property
    def max_daily_loss_wei(self) -> int:
        return int(self.max_daily_loss_bnb * Decimal(10) ** 18)

    def config_warnings(self) -> list[str]:
        """Hal-hal yang sah tapi berisiko. Bukan error, hanya peringatan."""
        warnings: list[str] = []
        if not self.daily_loss_limit_enabled:
            total = self.max_open_positions * self.buy_amount_bnb
            warnings.append(
                f"Rem rugi harian mati (MAX_DAILY_LOSS_BNB=0). Pembatas yang "
                f"tersisa cuma MAX_OPEN_POSITIONS={self.max_open_positions}, "
                f"yaitu {total} BNB berisiko pada satu waktu."
            )
        if self.sell_slippage_percent < 15:
            warnings.append(
                f"SELL_SLIPPAGE_PERCENT={self.sell_slippage_percent}% tergolong "
                f"ketat untuk penjualan. Trailing stop menembak saat harga jatuh "
                f"cepat, dan penjualan bisa revert. Perhatikan angka penjualan "
                f"gagal di tahap M4."
            )
        if self.sell_slippage_percent < self.buy_slippage_percent:
            warnings.append(
                f"Slippage jual ({self.sell_slippage_percent}%) lebih ketat "
                f"daripada slippage beli ({self.buy_slippage_percent}%). "
                f"Biasanya kebalikannya, karena jual yang gagal lebih merugikan "
                f"daripada beli yang gagal."
            )
        if self.gas_reserve_bnb < self.buy_amount_bnb:
            warnings.append(
                f"Cadangan gas ({self.gas_reserve_bnb} BNB) lebih kecil daripada "
                f"satu kali pembelian ({self.buy_amount_bnb} BNB). Pastikan cukup "
                f"untuk membayar gas semua penjualan yang mungkin terjadi."
            )
        return warnings

    @property
    def daily_loss_limit_enabled(self) -> bool:
        """MAX_DAILY_LOSS_BNB=0 berarti TANPA BATAS, bukan "berhenti di rugi 0".

        Ini ditulis eksplisit supaya tidak ada salah tafsir: angka 0 di
        baris itu mematikan rem harian sepenuhnya.
        """
        return self.max_daily_loss_bnb > 0

    @property
    def max_gas_price_wei(self) -> int:
        return int(self.max_gas_price_gwei * Decimal(10) ** 9)

    def summary_lines(self) -> list[str]:
        """Ringkasan aman untuk dicetak. Tidak pernah memuat rahasia."""
        mode = "SIMULASI (DRY_RUN=true, tidak ada uang keluar)" if self.dry_run \
            else "UANG SUNGGUHAN (DRY_RUN=false)"
        return [
            f"Mode                    : {mode}",
            f"Chain id                : {self.chain_id}",
            f"RPC baca data           : {self.rpc_read_url}",
            f"RPC kirim transaksi     : {self.rpc_private_url}",
            f"Router PancakeSwap      : {self.router_address}",
            f"Factory PancakeSwap     : {self.factory_address}",
            f"WBNB                    : {self.wbnb_address}",
            f"Dompet                  : {self.wallet_address or '(belum diset)'}",
            f"Private key             : {'ada, disembunyikan' if self.private_key else 'tidak ada'}",
            f"Beli per call           : {self.buy_amount_bnb} BNB",
            f"Maks posisi terbuka     : {self.max_open_positions}",
            f"Batas rugi per hari     : "
            + (f"{self.max_daily_loss_bnb} BNB" if self.daily_loss_limit_enabled
               else "TIDAK AKTIF (MAX_DAILY_LOSS_BNB=0)"),
            f"Batas gas price         : {self.max_gas_price_gwei} gwei",
            f"Slippage beli / jual    : {self.buy_slippage_percent}% / {self.sell_slippage_percent}%",
            f"Target ambil modal      : {self.take_profit_multiplier}x",
            f"Trailing stop           : turun {self.trailing_stop_percent}% dari puncak",
            f"Cadangan gas            : {self.gas_reserve_bnb} BNB",
            f"Channel dipantau        : {len(self.watch_chat_ids)} channel",
            f"Batas simulasi jual     : {self.sell_simulation_timeout_ms} ms",
            f"Database                : {self.database_path}",
        ]


@dataclass(frozen=True)
class NetworkConfig:
    """Bagian konfigurasi yang tidak menyangkut uang sama sekali.

    Dipakai oleh scripts/cek_jaringan.py, supaya skrip itu bisa jalan
    SEBELUM Anda mengisi angka-angka uang. Kalau tidak begini, ada
    lingkaran setan: MAX_GAS_PRICE_GWEI baru bisa Anda tentukan setelah
    tahu gas price sekarang, tapi skrip pengukurnya menolak jalan karena
    MAX_GAS_PRICE_GWEI belum diisi.
    """
    chain_id: int
    rpc_read_url: str
    rpc_private_url: str
    router_address: str
    factory_address: str
    wbnb_address: str


def load_network_config(env_path: Path | None = None) -> NetworkConfig:
    """Baca HANYA bagian jaringan dan alamat kontrak dari .env."""
    path = env_path or ENV_PATH
    if not path.exists():
        raise ConfigError(
            f"File .env tidak ditemukan di {path}\n"
            f"    Jalankan dulu:  cp .env.example .env"
        )
    load_dotenv(path, override=True)
    chain_id = _require_int("CHAIN_ID", "56 untuk BNB Smart Chain", minimum=1)
    if chain_id != 56:
        raise ConfigError(f"CHAIN_ID harus 56 (BNB Smart Chain), bukan {chain_id}.")
    return NetworkConfig(
        chain_id=chain_id,
        rpc_read_url=_require_str("RPC_READ_URL", "alamat RPC biasa untuk membaca data blockchain"),
        rpc_private_url=_require_str("RPC_PRIVATE_URL", "RPC privat anti-sandwich untuk mengirim transaksi"),
        router_address=_require_address("PANCAKE_ROUTER_ADDRESS", "alamat Router v2 PancakeSwap"),
        factory_address=_require_address("PANCAKE_FACTORY_ADDRESS", "alamat Factory v2 PancakeSwap"),
        wbnb_address=_require_address("WBNB_ADDRESS", "alamat token WBNB"),
    )


def load_config(env_path: Path | None = None) -> Config:
    """Baca .env dan kembalikan Config yang sudah diperiksa."""
    path = env_path or ENV_PATH
    if not path.exists():
        raise ConfigError(
            f"File .env tidak ditemukan di {path}\n"
            f"    Jalankan dulu:  cp .env.example .env\n"
            f"    lalu isi baris-baris yang bertanda ISI_SENDIRI."
        )
    load_dotenv(path, override=True)

    # --- saklar keselamatan: default AMAN ---
    dry_run = _parse_bool("DRY_RUN", default=True)

    chain_id = _require_int("CHAIN_ID", "56 untuk BNB Smart Chain", minimum=1)
    if chain_id != 56:
        raise ConfigError(
            f"CHAIN_ID harus 56 (BNB Smart Chain). Isinya sekarang {chain_id}.\n"
            f"    Bot ini hanya dibuat untuk BSC."
        )

    private_key = _raw("PRIVATE_KEY")
    register_secret(private_key)

    control_bot_token = _raw("CONTROL_BOT_TOKEN")
    register_secret(control_bot_token)

    telegram_api_hash = _raw("TELEGRAM_API_HASH")
    register_secret(telegram_api_hash)

    wallet_address = None
    if private_key:
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
            register_secret(private_key)
        if len(private_key) != 66:
            raise ConfigError(
                "PRIVATE_KEY panjangnya tidak benar. Yang benar 64 karakter hex "
                "(boleh diawali 0x). Periksa lagi isinya, jangan tempel alamat dompet."
            )
        try:
            from eth_account import Account
            wallet_address = Account.from_key(private_key).address
        except Exception as exc:  # nilai bukan kunci yang sah
            raise ConfigError(
                "PRIVATE_KEY tidak bisa dibaca sebagai private key yang sah. "
                "Periksa lagi isinya di file .env."
            ) from exc
    elif not dry_run:
        raise ConfigError(
            "DRY_RUN=false tapi PRIVATE_KEY kosong.\n"
            "    Mode uang sungguhan butuh private key. Isi baris PRIVATE_KEY di .env,\n"
            "    atau kembalikan DRY_RUN=true untuk mode simulasi."
        )

    cfg = Config(
        dry_run=dry_run,
        chain_id=chain_id,
        rpc_read_url=_require_str("RPC_READ_URL", "alamat RPC biasa untuk membaca data blockchain"),
        rpc_private_url=_require_str("RPC_PRIVATE_URL", "RPC privat anti-sandwich untuk mengirim transaksi"),
        router_address=_require_address("PANCAKE_ROUTER_ADDRESS", "alamat Router v2 PancakeSwap"),
        factory_address=_require_address("PANCAKE_FACTORY_ADDRESS", "alamat Factory v2 PancakeSwap"),
        wbnb_address=_require_address("WBNB_ADDRESS", "alamat token WBNB"),
        private_key=private_key,
        wallet_address=wallet_address,
        buy_amount_bnb=_require_decimal(
            "BUY_AMOUNT_BNB", "berapa BNB dibelanjakan untuk setiap call",
            minimum=Decimal("0"),
        ),
        max_open_positions=_require_int(
            "MAX_OPEN_POSITIONS", "maksimum posisi yang boleh terbuka bersamaan", minimum=1,
        ),
        max_daily_loss_bnb=_require_decimal(
            "MAX_DAILY_LOSS_BNB", "kalau rugi sehari sudah sebesar ini, bot berhenti beli",
            minimum=Decimal("0"),
        ),
        max_gas_price_gwei=_require_decimal(
            "MAX_GAS_PRICE_GWEI", "batas atas gas price, transaksi ditolak kalau melewati ini",
            minimum=Decimal("0"),
        ),
        buy_slippage_percent=_require_decimal(
            "BUY_SLIPPAGE_PERCENT", "toleransi selisih harga saat beli, dalam persen",
            minimum=Decimal("0"), maximum=Decimal("100"),
        ),
        sell_slippage_percent=_require_decimal(
            "SELL_SLIPPAGE_PERCENT", "toleransi selisih harga saat jual, dalam persen",
            minimum=Decimal("0"), maximum=Decimal("100"),
        ),
        take_profit_multiplier=_require_decimal(
            "TAKE_PROFIT_MULTIPLIER", "kelipatan modal untuk menarik modal awal, misal 3",
            minimum=Decimal("1"),
        ),
        trailing_stop_percent=_require_decimal(
            "TRAILING_STOP_PERCENT", "jual habis kalau harga turun sekian persen dari puncak",
            minimum=Decimal("0"), maximum=Decimal("100"),
        ),
        gas_reserve_bnb=_require_decimal(
            "GAS_RESERVE_BNB", "saldo BNB yang selalu disisakan untuk bayar gas jual",
            minimum=Decimal("0"),
        ),
        telegram_api_id=(int(_raw("TELEGRAM_API_ID")) if _raw("TELEGRAM_API_ID") else None),
        telegram_api_hash=telegram_api_hash,
        telegram_session_name=_raw("TELEGRAM_SESSION_NAME") or "sniper_listener",
        watch_chat_ids=_parse_chat_ids("WATCH_CHAT_IDS", "daftar id channel yang dipantau, dipisah koma"),
        control_bot_token=control_bot_token,
        owner_chat_id=(int(_raw("OWNER_CHAT_ID")) if _raw("OWNER_CHAT_ID") else None),
        blacklist_addresses=_parse_address_list("BLACKLIST_ADDRESSES"),
        sell_simulation_timeout_ms=_require_int(
            "SELL_SIMULATION_TIMEOUT_MS", "batas waktu simulasi jual dalam milidetik", minimum=50,
        ),
        log_level=(_raw("LOG_LEVEL") or "INFO").upper(),
        database_path=Path(_raw("DATABASE_PATH") or (PROJECT_ROOT / "data" / "sniper.db")),
        log_dir=Path(_raw("LOG_DIR") or (PROJECT_ROOT / "logs")),
    )
    return cfg
