# Hasil verifikasi pembangunan

Tanggal: 12 November 2026.

| Pemeriksaan | Hasil |
|---|---|
| Django system check | Lulus, 0 masalah |
| Migrasi dari database PostgreSQL kosong | Lulus, termasuk btree_gist, exclusion constraints, dan trigger immutable |
| `makemigrations --check --dry-run` | Lulus, tidak ada perubahan model yang belum dimigrasikan |
| Test suite final | **81 tes lulus**, sekitar 5,0 detik di lingkungan pengujian ini |
| Database suite final | **PostgreSQL 17.10 native**, Python 3.12.14, Django 5.2.19 |
| Transaksi paralel | Stok terakhir, jadwal dokter, callback payment duplikat, dan kuota delivery window lulus dengan koneksi terpisah |
| `check --deploy --fail-level WARNING` | Lulus pada konfigurasi production pemeriksaan; provider diset disabled, HTTPS/host/MFA flags diaktifkan |
| Audit 42 dependensi runtime terpin | 0 kerentanan yang dikenal menurut pip-audit pada saat pemeriksaan; detail `dependency-audit.json` |
| Pengumpulan static files | Lulus |
| Sintaks Python, JavaScript, SVG, struktur YAML | Diperiksa |
| `.gitignore` | `.env`, `.venv`, `var`, `staticfiles` terbukti diabaikan; migrations tetap ada |
| Browser publik | Halaman utama, filter spesies/kategori, keranjang, redirect Booking/Checkout tamu ke Login diperiksa |
| Screenshot | `screenshots/homepage.jpg` |

`check --deploy` adalah pemeriksaan konfigurasi framework, bukan bukti telah men-deploy, memasang TLS, menguji live provider, atau menyelesaikan pentest. Mode production aktual belum dijalankan untuk pelanggan nyata.

Docker daemon tidak tersedia pada lingkungan pembangunan ini. Compose dipersiapkan untuk PostgreSQL 17 dan diperiksa strukturnya; build image, startup seluruh container, dan workflow GitHub Actions belum dinyatakan lulus dari sesi ini. Jalankan perintah README di komputer Anda dan lakukan UAT dengan kredensial Sandbox.

SMTP internet, Google OAuth/Routes nyata, Midtrans Sandbox/live dan Biteship Testing/live belum diuji memakai akun proyek. Kontrak adapter diuji dengan mock; email OTP diuji melalui backend email memori. Tidak ada pembayaran, pengiriman paket, atau email ke inbox internet yang diklaim telah dilakukan.
