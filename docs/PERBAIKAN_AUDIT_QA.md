# Pembaruan perbaikan audit Sinau Satwa

Paket ini memperbaiki QA-01 dan QA-03 sampai QA-08 pada source. QA-02 (rotasi kredensial) masih memerlukan tindakan melalui akun provider Anda. Paket belum dipasang ke laptop atau website aktif Anda. Jangan menyatakan semua temuan telah ditutup sebelum pemasangan, rotasi, dan UAT selesai.

## Yang berubah

- QA-01: DEBUG bawaan false. DEBUG=true hanya efektif pada setup lokal dengan ALLOWED_HOSTS seluruhnya loopback dan tanpa URL webhook publik. Host publik/wildcard atau webhook publik menonaktifkan debug walaupun .env lama masih DEBUG=true.
- QA-03: quote menyimpan snapshot dan fingerprint asal toko. Perubahan alamat, koordinat, kontak, nama, atau pengesahan toko membatalkan tarif sebelum checkout. Sesudah pembayaran, perubahan asal menahan pembuatan pengiriman untuk penanganan admin. Tarif dispatch dihitung dari snapshot payload, bukan lokasi toko terbaru yang berbeda.
- QA-04: penolakan definitif pembuatan sesi pembayaran ditandai FAILED agar dapat dicoba kembali setelah penyebab diperbaiki. Timeout, respons ambigu, atau order ID sudah digunakan tetap UNKNOWN dan wajib direkonsiliasi agar tidak terjadi pembayaran ganda. HTTP 400 yang menyebut order_id diperlakukan konservatif sebagai ambigu.
- QA-05: attempt mencatat environment. MOCK dapat dinonaktifkan ketika beralih ke gateway; attempt uang nyata lintas environment tidak dipakai ulang atau direkonsiliasi dengan konfigurasi yang berbeda. Database sandbox dan produksi tetap harus terpisah.
- QA-06: daftar field tersembunyi dipakai bersama oleh exclude dan readonly. Tes mencakup render halaman admin Owner, Admin, dan Super Admin.
- QA-07: validasi pengesahan toko dan check_integrations memakai aturan yang sama: nama, alamat, koordinat/rentang, WhatsApp format 62, zona waktu IANA, serta jam buka/tutup.
- QA-08: tes concurrency memakai routing/shipping mock secara eksplisit dan tidak tergantung ORS key dari .env.

## Langkah pemasangan di Windows CMD

Contoh folder instalasi: C:\Users\Rizqi\sinau-satwa. Semua perintah berikut untuk CMD, bukan PowerShell.

### 1. Ekstrak paket di folder terpisah

Ekstrak ZIP terbaru ke:

C:\Users\Rizqi\sinau-satwa-update-audit

Pastikan file berikut ada:

C:\Users\Rizqi\sinau-satwa-update-audit\sinau-satwa\scripts\install_update.py

Jika aplikasi ekstraksi membuat lapisan folder tambahan, sesuaikan lokasi script dalam perintah. Jangan menimpa .env lama dengan file contoh.

### 2. Hentikan akses publik dan proses yang menulis data

Tutup tunnel ngrok dengan Ctrl+C. Buka CMD:

```bat
cd /d C:\Users\Rizqi\sinau-satwa
docker compose stop web worker beat
```

Biarkan database berjalan. Jika database belum berjalan:

```bat
docker compose up -d --wait db
```

### 3. Backup sebelum migrasi

```bat
mkdir var\audit-backup
copy .env var\audit-backup\environment-backup.txt
docker compose exec -T db pg_dump -U sinau -d sinau --no-owner --no-acl > var\audit-backup\before-audit.sql
docker compose cp web:/app/var/private var\audit-backup\private
```

Nama user/database pada contoh sesuai konfigurasi sinau yang digunakan sebelumnya. Bila Anda mengubahnya, sesuaikan -U dan -d. Pastikan setiap perintah berhasil, dump tidak kosong, dan berkas privat tersalin sebelum lanjut. Jika container web lama tidak tersedia, hentikan proses pembaruan dan backup volume private_data terlebih dahulu. Jangan menghapus volume untuk membuat ulang container.

Backup memuat data dan secret. Simpan privat; jangan dikirim ke chat atau GitHub. Folder var telah diabaikan Git. Gunakan nama folder backup berbeda bila sudah ada backup sebelumnya agar tidak menimpanya.

### 4. Periksa daftar perubahan

```bat
py C:\Users\Rizqi\sinau-satwa-update-audit\sinau-satwa\scripts\install_update.py --target C:\Users\Rizqi\sinau-satwa --dry-run
```

Installer mengganti file yang tercantum pada manifest. Jika Anda mengedit source sendiri sesudah paket sebelumnya, bandingkan perubahan terlebih dahulu. Installer mencadangkan file source lama yang diganti di var/update-backups, mempertahankan secret/configuration yang sudah ada dan tidak menghapus database/upload.

### 5. Pasang file pembaruan

```bat
py C:\Users\Rizqi\sinau-satwa-update-audit\sinau-satwa\scripts\install_update.py --target C:\Users\Rizqi\sinau-satwa
```

ROUTES_MODE yang sudah dipilih dipertahankan; nilai legacy google dimigrasikan ke openrouteservice. Nilai secret tidak dibuat ulang oleh installer.

### 6. Build dan migrasi sebelum menjalankan worker

```bat
docker compose build web worker beat
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose up -d --force-recreate --wait web worker beat
```

Dua migrasi baru: billing.0004_payment_environment dan delivery.0005_quote_origin. Jangan lanjut bila migrasi gagal. Jangan menjalankan docker compose down -v. Jangan menjalankan seed_demo untuk memperbaiki data yang sudah ada.

### 7. Pemeriksaan setelah pemasangan

```bat
docker compose ps
docker compose exec web python manage.py check
docker compose exec web python manage.py shell -c "from django.conf import settings; print('DEBUG efektif:', settings.DEBUG)"
docker compose exec web python manage.py check_integrations --strict
```

DEBUG efektif harus False untuk konfigurasi ngrok yang sudah Anda gunakan. Jika check_integrations menolak data toko, perbaiki data resmi melalui /management/ lalu sahkan kembali. Kegagalan karena data tidak valid kini memang sengaja diblokir.

Buka http://localhost:18000 dan alamat acak seperti /uji-halaman-tidak-ada/. Hasilnya harus 404 umum tanpa daftar URL dan tanpa informasi debug. Jalankan ngrok kembali hanya sesudah pemeriksaan ini berhasil.

### 8. Tangani transaksi sebelum pembaruan

Quote lama yang belum dibayar harus dihitung ulang. Order/invoice yang sudah terbentuk tidak dihapus otomatis. Bila quote lama sudah dibayar tetapi tidak memiliki identitas asal, pengiriman ditahan untuk pemeriksaan pengelola; jangan meminta pelanggan membayar lagi. Tentukan penanganan pesanan/refund melalui alur resmi setelah memeriksa transaksi.

Attempt MIDTRANS lama diberi environment hanya jika URL sesi membuktikan sandbox atau live. Attempt tanpa URL tetap tidak diketahui; jangan melabelinya sebagai live hanya karena .env sekarang live. Cocokkan order_id di dashboard provider dan konfigurasi asal sebelum rekonsiliasi. Attempt UNKNOWN tidak dibatalkan otomatis karena dapat memiliki dana/sesi di provider.

### 9. Uji alur pelanggan dan staf

Gunakan akun uji: Login, register/OTP, reset password, booking, boarding/perpanjangan, checkout pickup/delivery, rekam medis, dan ulasan. Uji Midtrans sandbox, webhook valid/duplikat, Biteship testing, serta alamat di dalam dan di luar batas rute. Pemeriksaan konfigurasi yang lulus tidak menggantikan UAT ini.

## Rotasi kredensial yang masih perlu Anda lakukan

Tidak ada kredensial dari percakapan yang dipakai atau disertakan dalam paket ini. Rotasi belum dapat dinyatakan selesai dari perubahan source.

1. Cabut App Password Gmail lama melalui akun Google, buat pengganti, lalu ubah EMAIL_HOST_PASSWORD dan pastikan EMAIL_HOST_USER benar.
2. Reset/rotasi GOOGLE_CLIENT_SECRET pada OAuth client yang digunakan. Client ID tetap sesuai OAuth client; jika membuat client baru, perbarui keduanya beserta redirect URI.
3. Rotasi server key Midtrans sesuai environment, Biteship API key dan secret webhook, serta ORS API key melalui akun masing-masing. Sesuaikan pengaturan webhook provider jika secret berubah. Jangan mencampur sandbox dan live.
4. Setelah setiap perubahan konfigurasi, recreate web/worker/beat dan uji layanan terkait. Hindari rotasi pada saat transaksi masih berlangsung tanpa jadwal dan penanganan callback yang jelas.
5. SECRET_KEY Django perlu diganti dengan nilai acak kuat melalui prosedur yang direncanakan; sesi dan tautan bertanda tangan lama dapat menjadi tidak berlaku. Jangan menganggap hanya mengganti key provider sudah mencakup key aplikasi.
6. DATA_ENCRYPTION_KEY tidak boleh diganti langsung: data terenkripsi lama dapat tidak terbaca. Siapkan backup dan migrasi re-enkripsi seluruh field terkait di lingkungan terpisah lebih dahulu. Password PostgreSQL juga perlu diubah pada role database dan DATABASE_URL/POSTGRES_PASSWORD secara selaras; perubahan .env saja tidak mengubah password role pada volume database lama.

Jangan mengirim nilai key/password baru atau file .env. Verifikasi cukup melalui hasil pemeriksaan yang tidak memuat secret. Selama rotasi belum dituntaskan, QA-02 tetap terbuka. Untuk dua key yang memerlukan migrasi data/database, lakukan sebagai pekerjaan terjadwal dengan uji restore, bukan penggantian sembarang saat aplikasi berjalan.

## Hasil pengujian paket

- PostgreSQL 17 terpisah, tanpa kredensial pengguna: 122/122 tes lulus, termasuk 15 tes tambahan untuk regresi, installer, dan migrasi database lama.
- Django check, migrasi, makemigrations --check --dry-run, serta collectstatic berhasil.
- check --deploy --fail-level WARNING lulus dengan konfigurasi produksi uji; ini hanya validasi setting, bukan pengujian hosting atau API provider nyata.
- Suite dijalankan dengan konfigurasi installer baru (ROUTES_MODE=openrouteservice tanpa key); tes internal tidak memerlukan internet provider.
- Tidak ada dependency baru. Pemindaian dependensi pada audit sebelumnya tetap merupakan snapshot advisori pada waktu audit.
- Docker laptop, akun provider, penampilan mobile, dan website aktif belum diuji ulang setelah pemasangan karena paket belum dipasang di laptop Anda. Ini bukan sertifikasi bebas celah atau persetujuan produksi.

## Pemulihan bila pembaruan bermasalah

Hentikan web/worker/beat. Simpan log tanpa secret dan gunakan backup source yang dicatat installer. Migrasi rilis ini menambah kolom dan tidak menghapus data lama; jangan menghapus volume. Pemulihan database perlu dilakukan pada database kosong/terpisah menggunakan dump yang telah dibuat dan mencocokkan backup berkas privat serta kunci enkripsi. Verifikasi restore sebelum mengganti database operasional.
