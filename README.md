# Sinau Satwa

Aplikasi dinamis untuk satu lokasi petshop. Dibangun dengan Python 3.12, Django 5.2 LTS, PostgreSQL 17, Django Templates, CSS dengan token desain, Celery, dan Redis. Pelanggan dan staf menggunakan **satu halaman Login**. Website ini belum dipublikasikan.

Peta tanpa billing Google: [PETA_GRATIS.md](docs/PETA_GRATIS.md). Leaflet/OpenStreetMap dapat tampil langsung; rute jalan nyata memerlukan key ORS Standard gratis.

Integrasi eksternal lokal/production: [panduan lengkap](docs/INTEGRASI_LOCAL_PRODUCTION.md). Revisi ini memisahkan URL kembali pelanggan dan webhook, serta menambahkan `check_integrations`.

## Jalankan di localhost

Siapkan Docker Desktop dengan Linux containers dan Docker Compose v2, serta Python 3.12 untuk membuat konfigurasi awal. Buka terminal di folder yang memuat `manage.py` dan `compose.yaml`.

Windows PowerShell:

```powershell
py scripts/init_local.py
docker compose up -d --build
docker compose ps
docker compose exec web python manage.py seed_demo
```

Linux/macOS: ganti perintah pertama menjadi `python3 scripts/init_local.py`. Bila UID/GID Linux Anda berbeda dari 1000, sesuaikan `LOCAL_UID`/`LOCAL_GID` pada `.env` sebelum build.

Build pertama mengunduh image dan dependensi. Web menjalankan migrasi dan `collectstatic` otomatis. Tunggu status web **healthy** sebelum menjalankan seed. Jika `exec` terlalu cepat, tunggu sampai web siap lalu ulangi perintah seed; data yang sudah ada tidak ditimpa.

- Website: <http://localhost:18000>
- Login pelanggan dan staf: <http://localhost:18000/login/>
- Kotak email pengujian Mailpit: <http://localhost:18025>
- Data master: <http://localhost:18000/management/>, sesudah Login dengan peran yang berwenang.

`init_local.py` membuat `.env` sekali dengan secret, kunci enkripsi, password database, dan password demo acak. Script tidak menimpa konfigurasi yang sudah ada. **Jangan commit `.env`.**

## Akun pengujian

Semua akun berikut memakai nilai `DEMO_PASSWORD` pada `.env` Anda. Tidak ada password universal yang dibagikan di kode.

| Peran | Email | Dashboard setelah Login |
|---|---|---|
| Pelanggan | `customer@sinau.test` | `/dashboard/` |
| Super Admin | `super_admin@sinau.test` | `/staf/super-admin/` |
| Owner Usaha | `owner@sinau.test` | `/staf/owner/` |
| Admin Operasional | `admin@sinau.test` | `/staf/admin/` |
| Dokter Hewan | `doctor@sinau.test` | `/staf/dokter/` |
| Groomer | `groomer@sinau.test` | `/staf/grooming/` |
| Petugas Penitipan | `caretaker@sinau.test` | `/staf/penitipan/` |

Peran ditentukan setelah autentikasi berhasil. Mengganti URL atau mengirim field role saat Register tidak memberikan akses staf. Akun dengan beberapa peran dapat mengganti workspace ke peran yang memang dimilikinya. Owner memiliki akses lihat. Demo Admin memiliki izin tambahan pengantaran.

## Yang dapat diuji

1. Register → OTP email → verifikasi → Login. Forgot password juga memakai OTP email, lalu mencabut sesi lama setelah password diganti.
2. Profil hewan, foto, alamat lengkap, titik Maps, kontak penerima, dan kontak darurat.
3. Booking dokter/grooming dengan reservasi staf/fasilitas, shift, buffer, pembayaran, perubahan jadwal, dan penyelesaian layanan.
4. Dokter menyimpan draft, menerbitkan diagnosis serta panduan, mengunggah foto/PDF, membuat revisi versi baru, dan menentukan kontrol. PDF pelanggan tidak memuat catatan internal dokter.
5. Penitipan: unggah dan verifikasi dokumen → tinjauan unit → tagihan → check-in → kabar harian → perpanjangan disetujui/ditolak → tagihan tambahan → perubahan waktu jemput setelah dibayar → check-out.
6. Katalog dengan filter jenis hewan dan kategori yang saling sesuai; keranjang; Checkout ambil di toko atau pengiriman.
7. Persediaan per batch, FEFO, reservasi stok, ledger penerimaan/penyesuaian, dan kasir yang memakai stok yang sama dengan online.
8. Kurir Toko berdasarkan batas rute dan kuota window, atau kurir instan; penugasan, mulai antar, bukti serah terima, dan pelacakan status.
9. Tagihan, simulasi pembayaran lokal, adapter Midtrans, penerimaan tunai, rekonsiliasi, dana ganda yang belum diterapkan, dan alur persetujuan refund dengan referensi pengembalian.
10. Ulasan dari transaksi selesai dan dibayar, moderasi beralasan, laporan CSV, notifikasi, audit, serta pengaturan akun/peran.

## Email dan integrasi nyata

**Konfigurasi awal menggunakan Mailpit, simulasi pembayaran/kurir, peta Leaflet/OpenStreetMap dan adapter rute ORS.** Mailpit menangkap email di komputer Anda; email tersebut belum masuk Gmail atau inbox internet. Untuk OTP email nyata, isi SMTP yang sah, akun pengirim, autentikasi, TLS, dan domain pengirim pada `.env`. Backend yang sama mengirim OTP registrasi, Forgot password, serta undangan staf melalui SMTP tersebut.

Midtrans Sandbox, Google Login, openrouteservice/HeiGIT, dan Biteship mempunyai adapter backend serta konfigurasi terpisah. Isi kredensial provider Anda untuk uji integrasi. Login Google disembunyikan sampai konfigurasi tersedia. `ROUTES_MODE=mock` tetap tersedia hanya untuk fixture pengujian eksplisit. Jika ORS key kosong, Kurir Toko tidak ditawarkan berdasarkan jarak palsu. Radius 5 km dan harga seed hanyalah data contoh.

Panduan rinci: [INTEGRATIONS.md](docs/INTEGRATIONS.md). Alur refund saat ini mencatat permintaan, persetujuan, dan referensi rekonsiliasi. Pengembalian dana melalui bank/provider dilakukan operator; aplikasi tidak mengklaim sudah mentransfer dana hanya karena tombol persetujuan ditekan.

## Pengujian

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py test tests --noinput -v 2
```

Tes memakai database PostgreSQL terpisah yang dibuat oleh Django. Termasuk dua koneksi paralel untuk stok terakhir dan jadwal dokter. Pengujian HTTP provider menggunakan mock terkontrol; transaksi nyata tidak dijalankan oleh test suite. Hasil dan batas verifikasi ada di [TESTING.md](docs/TESTING.md).

Jika OTP belum muncul setelah beberapa detik:

```powershell
docker compose logs --tail=50 worker beat
docker compose exec web python manage.py run_maintenance
```

Satu siklus maintenance dapat dijalankan manual tanpa Redis melalui command tersebut. Dalam Compose, Celery Beat menjadwalkannya setiap 30 detik. Jangan menjalankan beberapa Beat untuk lingkungan yang sama.

## Struktur folder

| Folder | Tanggung jawab |
|---|---|
| `config/` | Settings lingkungan, URL, WSGI/ASGI, Celery |
| `accounts/` | User, OTP, Login Google, MFA, peran, middleware |
| `customers/` | Pelanggan, profil hewan, alamat, kontak darurat |
| `catalog/` | Produk, SKU, jenis hewan, kategori |
| `inventory/` | Batch, reservasi dan ledger stok |
| `orders/` | Keranjang, Checkout, snapshot, pesanan, serah terima |
| `scheduling/` | Layanan, shift, resource, Booking, reservasi waktu |
| `care/` | Pemeriksaan, versi medis, PDF, grooming |
| `boarding/` | Unit, intake, masa inap, perpanjangan, kabar harian |
| `billing/` | Invoice, payment, webhook Midtrans, refund |
| `delivery/` | Rute, quote, kuota, shipment, Biteship, kurir karyawan |
| `engagement/` | Ulasan, reminder, log notifikasi |
| `core/` | Audit, berkas privat, outbox, operasi bersama |
| `templates/`, `static/` | Antarmuka, token desain, JavaScript, aset lokal |
| `tests/`, `docs/`, `scripts/` | Verifikasi, panduan, utilitas pengembangan |

Aturan transaksi ada di `services.py`; query akses bersama di `core/selectors.py`; input melalui forms; provider HTTP terpisah dari transaksi database. Django management digunakan untuk master data. Status bisnis tidak diedit langsung melalui management.

## GitHub dan perawatan

`.gitignore` sudah mencakup secret, virtualenv, cache, data pribadi, file upload, database, log, dan hasil build. **Migrations, `.env.example`, source, serta lisensi aset tetap dilacak.** Periksa `git status` sebelum commit. Workflow GitHub Actions disediakan untuk menguji dengan PostgreSQL 17 setelah Anda push; workflow tersebut belum dijalankan dari sesi ini.

```powershell
docker compose down
docker compose up -d
```

`down` tanpa `-v` mempertahankan data. Jangan memakai `down -v` jika database dan berkas perlu dipertahankan. Perubahan konfigurasi lingkungan memerlukan `docker compose up -d --force-recreate web worker beat`; perubahan dependensi memerlukan `--build`.

Untuk data usaha pertama tanpa seed, konfigurasikan SMTP lalu jalankan:

```powershell
docker compose exec web python manage.py bootstrap_admin --email email-anda@example.com --name "Nama Pengelola"
```

Email undangan berisi OTP dan tautan untuk mengatur password. Selesaikan sebelum kode berakhir; akun yang belum terverifikasi dapat dipulihkan melalui Forgot password bila perlu.

Mode production memerlukan konfigurasi HTTPS, hostname eksplisit, MFA staf, kredensial provider, backup, dan kebijakan usaha yang disahkan. Compose ini ditujukan untuk localhost. Lihat [SECURITY.md](docs/SECURITY.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), dan [OPEN_DECISIONS.md](docs/OPEN_DECISIONS.md).


## Perbaikan audit QA

Lihat [panduan pembaruan dan status temuan](docs/PERBAIKAN_AUDIT_QA.md).


## Pembaruan UI/UX dan alur pengguna

Lihat [panduan pemasangan dan perubahan fitur](docs/UPDATE_PENGALAMAN.md) serta [referensi desain](docs/REFERENSI_DESAIN.md). Data master kini menggunakan /pengaturan/.


Pembaruan katalog dan konten dinamis: lihat [panduan update](docs/UPDATE_DINAMIS.md) untuk pemasangan aman, pengelolaan logo/konten, dan publikasi produk terpadu.
