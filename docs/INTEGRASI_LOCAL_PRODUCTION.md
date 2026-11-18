# Integrasi eksternal: localhost dan production

Revisi 16 November 2026. Source mendukung SMTP, Midtrans Snap, Google OIDC Login, Leaflet/OpenStreetMap/ORS, Biteship, Maps lokasi toko, dan tautan WhatsApp CS. Integrasi aktif ketika kredensial dan pengaturan penyedia diisi. Tidak ada kredensial pengguna dalam paket. Semua transaksi pengujian pembayaran dan pengiriman menggunakan akun Sandbox/Testing; Peta/rute memakai layanan gratis dengan kuota/kebijakan penyedia; SMTP mengikuti penyedia email. Lihat PETA_GRATIS.md untuk revisi peta terbaru.

## Pembagian alamat

- `APP_URL` adalah origin yang dibuka pelanggan, dipakai untuk email, Google callback, dan kembali dari Midtrans. Pilih satu origin selama sesi: untuk komputer yang sama, gunakan `http://localhost:18000`.
- `PUBLIC_WEBHOOK_BASE_URL` adalah origin HTTPS publik penerima webhook, misalnya URL ngrok AKTIF. Boleh berbeda dari APP_URL. Untuk production biasanya kedua origin sama dengan domain HTTPS toko.
- URL kembali pembayaran: `APP_URL/pembayaran/kembali/`. Alias `/cek-pesanan` juga didukung. Parameter `transaction_status=settlement` tidak melunasi tagihan. Pelanggan harus Login sebagai pemilik; tombol POST Periksa ke Midtrans, worker, atau webhook yang diverifikasi mengambil status otoritatif.
- Notification Midtrans: `PUBLIC_WEBHOOK_BASE_URL/webhooks/midtrans/`. Backend menyertakan `X-Override-Notification` pada sesi Snap baru bila public URL diatur. URL kembali dikirim dalam `callbacks.finish` dan `callbacks.error`; sesi lama bisa menyimpan URL lama, jadi buat sesi/pesanan uji baru setelah konfigurasi diperbaiki.
- Webhook Biteship: `PUBLIC_WEBHOOK_BASE_URL/webhooks/biteship/`. Atur URL dan pasangan header rahasia pada dashboard Biteship.
- Google redirect: `APP_URL/auth/google/callback/`. Harus sama persis di Google Cloud, termasuk skema, hostname, port dan trailing slash.

ERR_NGROK_3200 berarti endpoint tidak online/ditemukan; kode aplikasi tidak dapat menyalakan tunnel pada komputer pengguna. Buka terminal kedua, jalankan `ngrok http 18000`, lalu biarkan proses hidup. Jika domain tunnel berubah, perbarui PUBLIC_WEBHOOK_BASE_URL, ALLOWED_HOSTS, dashboard Biteship, dan pengaturan notifikasi Midtrans. Jangan memakai URL lama dari screenshot sebagai URL baru.

## Upgrade instalasi yang sudah berjalan

Ekstrak paket baru ke folder terpisah, misalnya `C:\Users\Rizqi\sinau-satwa-update`. Jangan mengekstrak langsung di atas instalasi lama.

```powershell
py C:\Users\Rizqi\sinau-satwa-update\scripts\install_update.py --target C:\Users\Rizqi\sinau-satwa --dry-run
docker compose -f C:\Users\Rizqi\sinau-satwa\compose.yaml stop web worker beat
py C:\Users\Rizqi\sinau-satwa-update\scripts\install_update.py --target C:\Users\Rizqi\sinau-satwa
```

Jika ZIP mengekstrak satu folder `sinau-satwa` tambahan, sesuaikan path script. Installer menyalin file revisi yang terdaftar saja, menyimpan salinan file lama yang berubah dalam `var/update-backups`, dan menambahkan setting baru yang belum ada. Revisi peta gratis juga memigrasikan ROUTES_MODE menjadi openrouteservice. Password SMTP, secret, API key, pengaturan .env yang sudah ada, database dan upload dipertahankan. Compose lokal diganti dengan versi yang mendukung WEB_PORT/MAILPIT_WEB_PORT; bandingkan backup bila sebelumnya membuat perubahan Compose selain port. Revisi peta gratis menambahkan migrasi delivery.0004_routeestimate; Compose lokal menjalankannya otomatis.

## Localhost dengan layanan nyata

1. Pertahankan `.env` Anda dan gunakan `env/local-real.example` sebagai daftar setting, bukan file pengganti secret/database. Isi semua kredensial akun proyek Anda.
2. Jalankan `ngrok http 18000` di terminal terpisah. Salin URL HTTPS aktual dari output ngrok.
3. Isi konfigurasi berikut. Ganti `DOMAIN-NGROK-AKTIF` dengan hostname sebenarnya, tanpa wildcard:

```dotenv
DEPLOYMENT_MODE=local
WEB_PORT=18000
MAILPIT_WEB_PORT=18025
APP_URL=http://localhost:18000
PUBLIC_WEBHOOK_BASE_URL=https://DOMAIN-NGROK-AKTIF
ALLOWED_HOSTS=localhost,127.0.0.1,[::1],DOMAIN-NGROK-AKTIF
CSRF_TRUSTED_ORIGINS=http://localhost:18000,http://127.0.0.1:18000
PAYMENT_MODE=midtrans_sandbox
ROUTES_MODE=openrouteservice
SHIPPING_MODE=biteship
```

4. Midtrans: isi Sandbox Server Key dan Client Key; pada dashboard Sandbox atur Payment Notification URL ke URL webhook di atas, dan Finish/Error Redirect URL ke `http://localhost:18000/pembayaran/kembali/`. Sesi baru mengirim URL kembali dengan referensi order secara otomatis. Pakai simulator Sandbox, bukan transfer nyata.
5. Google Login: buat OAuth Client Web Application khusus pengembangan. Daftarkan redirect URI `http://localhost:18000/auth/google/callback/`, isi GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET. Lengkapi consent screen/audience dan pengguna uji sesuai status aplikasi Google Anda. Lakukan Login dari localhost yang sama; jangan berpindah antara ngrok, 127.0.0.1 dan localhost di tengah alur karena session/cookie berbeda. Login pelanggan tidak memberikan peran staf.
6. Peta gratis: Leaflet/OpenStreetMap tampil tanpa Google API key. Isi ORS_API_KEY dari akun Standard gratis HeiGIT dan ORS_BASE_URL=https://api.heigit.org. Ikuti [PETA_GRATIS.md](PETA_GRATIS.md) untuk cache, kuota, sumber tile dan batas penggunaan production.
7. Biteship: aktifkan Testing Mode pada dashboard, ambil API Key Test, isi BITESHIP_API_KEY. Testing dan Live menggunakan host API yang sama; jenis key menentukan lingkungan sebenarnya. Pada dashboard atur webhook serta header name/secret sesuai BITESHIP_WEBHOOK_HEADER/BITESHIP_WEBHOOK_SECRET. Isi data asal toko, nomor kontak, titik lokasi, berat dan dimensi produk yang valid. Testing tetap mengikuti ketersediaan cakupan akun/kurir; kosongnya tarif tidak boleh diganti tarif palsu.
8. SMTP nyata: pertahankan konfigurasi yang sudah berhasil. Gmail memakai App Password akun pengirim, misalnya port 465 + SSL atau 587 + TLS, tidak keduanya. EMAIL_TIMEOUT bisa diatur. Jangan kirim secret lewat chat. Jika Wi-Fi memblokir SMTP, koneksi hotspot yang berhasil tetap diperlukan sampai jaringan diperbaiki; localhost tidak menghilangkan syarat konektivitas provider.
9. Kontak publik: Super Admin membuka data master Store Settings, isi alamat resmi, koordinat, dan cs_whatsapp dengan format internasional angka saja (`62...`), lalu sahkan `public_contact_ready`. Tautan WhatsApp membuka chat di WhatsApp; bukan pengiriman pesan otomatis. Embed Maps lokasi toko berbeda dari key Routes pengiriman.
10. Terapkan dan periksa:

```powershell
docker compose up -d --build --wait
docker compose exec web python manage.py check_integrations --strict
docker compose exec web python manage.py check_integrations --network --strict
```

Command pertama memeriksa konfigurasi dan data kontak, kedua juga menguji TLS host provider, endpoint publik /health/ dan autentikasi SMTP. Tidak mengirim email, membuat pembayaran atau memesan kurir. TLS OK bukan bukti key API benar. Jangan menganggap readiness sebagai UAT berhasil.

Jika Anda ingin membuka website lewat ngrok/HP, ganti APP_URL ke origin ngrok aktif, daftarkan origin tersebut di CSRF_TRUSTED_ORIGINS dan Google redirect URI, recreate container, lalu mulai Login baru dari origin itu. localhost pada HP menunjuk ke HP sendiri. Bila memakai HTTPS melalui proxy, set TRUST_PROXY_HTTPS=true hanya bila proxy dipercaya dan menimpa X-Forwarded-Proto; backend harus tidak bisa diakses publik secara langsung.

## Production

1. Gunakan host/server dengan Docker, PostgreSQL persistent, domain HTTPS, reverse proxy TLS, backup yang diuji, dan secret terpisah dari lingkungan uji. Jangan memakai database pengujian untuk pelanggan nyata. `env/production.example` adalah daftar konfigurasi, bukan kredensial siap pakai.
2. Set DEPLOYMENT_MODE=production, DEBUG=false, APP_URL/PUBLIC_WEBHOOK_BASE_URL ke domain HTTPS resmi, ALLOWED_HOSTS eksplisit, CSRF_TRUSTED_ORIGINS ke origin HTTPS tersebut, REQUIRE_STAFF_MFA=true, PAYMENT_MODE=midtrans_live. Isi key Production Midtrans, Live Biteship, Google OAuth production dan key ORS Standard milik pengelola, serta SMTP resmi. Merchant/account/layanan harus disetujui provider. Jangan mencampur Sandbox/Testing dengan data operasional.
3. Pakai compose.production.yaml, yang menggunakan Gunicorn, tanpa source bind mount, tanpa Mailpit, tanpa port database/Redis publik. Nginx/TLS reverse proxy pada host meneruskan ke 127.0.0.1:18000 dan harus menimpa X-Forwarded-Proto. Baru aktifkan TRUST_PROXY_HTTPS=true. Tidak ada deploy otomatis yang dilakukan dari sesi pengembangan ini.

```bash
docker compose -f compose.production.yaml build
docker compose -f compose.production.yaml up -d db redis
docker compose -f compose.production.yaml run --rm web python manage.py migrate --noinput
docker compose -f compose.production.yaml run --rm web python manage.py collectstatic --noinput
docker compose -f compose.production.yaml run --rm web python manage.py check --deploy --fail-level WARNING
docker compose -f compose.production.yaml run --rm web python manage.py check_integrations --strict
docker compose -f compose.production.yaml up -d web worker beat
```

Siapkan akun pertama melalui bootstrap_admin sesuai README, isi master toko, lalu ulangi check_integrations --strict sesudah konfigurasi data lengkap. Tidak perlu seed_demo di production. Bila strict masih gagal, selesaikan setiap isu sebelum menerima pelanggan. Compose production tidak menyediakan reverse proxy/sertifikat otomatis; pasang pada server Anda. Jika memakai proxy container, gunakan jaringan internal yang tepat dan pertahankan pembatasan akses backend.

## UAT wajib per integrasi

- Register dan Forgot password: kode masuk inbox nyata, hanya kode terakhir berlaku, habis masa berlaku/percobaan ditolak. Uji setelah SMTP dan worker sudah aktif, bukan hanya send_mail manual.
- Google Login: pelanggan baru, tautan eksplisit pelanggan lama, penolakan akun yang tidak berhak sebagai staf, error/cancel consent. Login Google tidak memberikan izin otomatis mengirim email via Gmail.
- Maps: tampilkan peta Leaflet/OpenStreetMap dengan attribution, pilih pin, alamat/kontak lengkap, tarif internal dari rute backend aktual; uji tepat di batas 5 km contoh dan di luar cakupan. Nilai 5 km adalah kebijakan toko yang dapat diubah.
- Midtrans: buat pesanan baru, bayar Sandbox, kembali ke tagihan, cek authenticated GET dan webhook. Coba URL kembali yang dipalsukan settlement: tagihan tidak boleh langsung lunas. Uji callback duplikat, pembayaran terlambat dan jaringan putus. URL lama yang tersimpan pada sesi sebelumnya tidak dapat diperbaiki retroaktif oleh kode baru.
- Biteship: tarif Testing, dispatch referensi sama, polling, webhook dengan secret benar/salah, delivered/canceled sesuai simulator provider. Jangan menguji key Live dengan tombol dispatch kecuali memang menghendaki pengiriman berbayar.
- WhatsApp/lokasi: tautan menuju nomor CS dan lokasi yang telah disahkan klien.

## Referensi resmi

- https://ngrok.com/docs/errors/err_ngrok_3200
- https://docs.midtrans.com/reference/json-objects
- https://docs.midtrans.com/docs/https-notification-webhooks
- https://support.google.com/cloud/answer/15549257
- https://developers.google.com/maps/api-security-best-practices
- https://help.biteship.com/hc/id/articles/39554706133913-Cara-Menggunakan-Mode-Sandbox-atau-Testing-di-Biteship

Verifikasi source dan mock tidak membuktikan akun provider proyek sudah aktif. Kredensial, billing/kuota, jaringan, tunnel dan domain harus disiapkan pemilik proyek; pengujian end-to-end provider nyata dilakukan dengan akun tersebut.
