# Sniper Bot PancakeSwap (BNB Smart Chain)

Bot yang memantau channel Telegram berisi call token, membeli otomatis di
PancakeSwap, menarik modal awal saat harga 3x, lalu sisanya dikelola manual
lewat perintah Telegram.

> **Status saat ini: tahap M1 selesai.**
> Bot belum membaca Telegram dan belum membeli apa pun. Yang sudah jadi
> adalah kerangkanya: konfigurasi, database, dan logging.

---

## Aturan keselamatan yang dipegang bot ini

1. `DRY_RUN=true` adalah bawaan. Kalau baris itu hilang dari `.env`, bot
   tetap masuk mode simulasi. Kalau isinya bukan `true`/`false`, bot
   menolak jalan. Uang sungguhan hanya jalan kalau Anda sendiri menulis
   `DRY_RUN=false`.
2. Private key hanya dibaca dari `.env`, tidak pernah muncul di log.
   Sudah ada uji otomatis yang membuktikan ini.
3. Ada batas rugi harian dan batas jumlah posisi terbuka (`.env`).
4. Beli/jual yang gagal diulang otomatis dengan gas lebih tinggi
   (dikerjakan di tahap M3).

---

## Isi folder

```
snipertelegram/
├── .env.example          <- contoh konfigurasi, SALIN jadi .env lalu isi
├── .env                  <- konfigurasi asli Anda (tidak pernah masuk git)
├── requirements.txt      <- daftar paket Python
├── sniper/
│   ├── config.py         <- membaca & memeriksa .env
│   ├── db.py             <- database SQLite
│   └── logging_setup.py  <- logging + sensor private key
├── scripts/
│   └── m1_check.py       <- pemeriksaan tahap M1
├── data/sniper.db        <- database (dibuat otomatis)
└── logs/sniper.log       <- catatan kegiatan bot
```

---

## Cara menyiapkan (sekali saja)

Jalankan perintah ini satu per satu di terminal, dari dalam folder proyek.

```bash
# 1. buat lingkungan Python terpisah
python3 -m venv .venv

# 2. aktifkan
source .venv/bin/activate

# 3. pasang paket yang dibutuhkan
pip install -r requirements.txt

# 4. buat file konfigurasi Anda
cp .env.example .env
```

Lalu buka file `.env` dengan editor teks dan isi setiap baris yang
bertuliskan `ISI_SENDIRI`.

---

## Cara memeriksa apakah semuanya beres

```bash
source .venv/bin/activate
python3 scripts/m1_check.py
```

Kalau ada yang kurang, skrip ini akan menyebut **nama baris di `.env`**
yang harus Anda perbaiki. Kalau semua beres, di baris terakhir muncul
`M1 SELESAI`.

---

## Tabel di database

| Tabel            | Isinya                                                   |
|------------------|----------------------------------------------------------|
| `token_registry` | setiap token yang pernah terlihat, dipakai untuk dedupe   |
| `calls`          | setiap pesan channel yang memuat alamat kontrak           |
| `positions`      | posisi token yang dipegang, modal, harga puncak, status   |
| `trades`         | setiap percobaan transaksi, termasuk percobaan ulang      |
| `daily_stats`    | untung/rugi per hari, dipakai untuk batas rugi harian     |
| `bot_state`      | keadaan bot yang bertahan setelah restart, mis. pause     |

Semua jumlah token dan BNB disimpan sebagai **teks**, bukan angka, karena
jumlah token bisa melebihi batas angka bulat SQLite.

Posisi simulasi (`dry_run=1`) dan posisi uang sungguhan (`dry_run=0`)
dipisah di kolom yang sama, jadi hasil latihan tidak pernah tercampur
dengan uang asli.

---

## Tahapan pengerjaan

| Tahap | Isi                                                        | Status  |
|-------|------------------------------------------------------------|---------|
| M1    | kerangka proyek, `.env`, database, logging                  | selesai |
| M2    | pendengar Telegram, mencatat call ke database               | belum   |
| M3    | simulasi jual (`eth_call`) + beli dalam mode DRY_RUN        | belum   |
| M4    | manajer posisi: 3x, hitung porsi modal, trailing stop       | belum   |
| M5    | perintah manual lewat bot Telegram pribadi                  | belum   |
| M6    | mode uang sungguhan, systemd, panduan pemakaian             | belum   |
