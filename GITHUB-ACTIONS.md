# Jurnal Sync via GitHub Actions

Runner Windows gratis, tiap 6 jam: install MT5 -> login investor -> tarik history -> POST ke Worker -> VM dihapus.

## Setup (sekali saja)

### 1. Buat repo

Repo **publik** supaya menit Actions-nya tidak terbatas. Kode di sini tidak rahasia — semua kredensial disimpan di Secrets, bukan di file.

Struktur:

```
repo/
  .github/workflows/jurnal.yml
  sync_ci.py
```

### 2. Isi Secrets

Repo -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**:

| Nama | Nilai |
|---|---|
| `MT5_LOGIN` | nomor akun investor |
| `MT5_SERVER` | mis. `Exness-MT5Real8` |
| `MT5_PASSWORD` | password **investor** |
| `JOURNAL_ENDPOINT` | `https://jurnal-trade.philipsyahmi82.workers.dev/api/ingest` |
| `JOURNAL_TOKEN` | token `INGEST_SECRET` |

### 3. Jalankan manual sekali

Repo -> tab **Actions** -> **Jurnal Sync** -> **Run workflow**.

Cek log. Yang harus muncul di akhir:

```
History siap: 123 trade (percobaan 1)
123 trade, net 1,234.56 -> HTTP 200 ok
```

Kalau `HTTP 401` -> `JOURNAL_TOKEN` salah. Kalau `Login gagal` -> cek `MT5_SERVER` dan password investor. Kalau `History belum tersedia` sampai habis -> naikkan `--tries` atau `--delay`.

### 4. Biarkan jadwal jalan

Setelah manual run hijau, cron `0 */6 * * *` akan jalan sendiri.

## Batasan yang harus kamu tahu

- **Jadwal bisa dimatikan GitHub setelah 60 hari tanpa aktivitas repo.** Kalau kamu tidak pernah push/commit apa pun selama 2 bulan, workflow terjadwal berhenti otomatis. Solusi: sesekali buka repo dan commit apa saja, atau jalankan manual.
- **Cron tidak presisi.** GitHub menunda jadwal saat antrean ramai — bisa 5-20 menit, kadang terlewat satu siklus. Untuk jurnal, ini tidak masalah.
- **Tiap run install MT5 dari nol** (~3-5 menit dari total run). Itu harga dari "gratis tanpa mesin".
- **History diunduh ulang tiap run.** Akun dengan history panjang butuh waktu; script sudah menunggu sampai 15 x 12 detik.
- **Repo publik = log publik.** Jangan pernah `print` password atau token di script. Script ini tidak melakukannya.
- **Kalau MT5 mengubah URL installer**, step install akan gagal dan perlu URL baru. Ini titik paling rapuh dari jalur ini.

## Kalau mau lebih sering dari 6 jam

Ubah cron, misal tiap 2 jam: `0 */2 * * *`. Tapi ingat: tiap run memakan waktu ~5 menit dan GitHub membatasi frekuensi. 6 jam adalah titik seimbang untuk jurnal.

## Verifikasi

Buka https://jurnal-trade.philipsyahmi82.workers.dev — waktu sinkron terakhir tampil di kanan atas halaman.
