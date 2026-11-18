# Integrasi dan pengujian lokal

## Email OTP

Default: `EMAIL_HOST=mailpit`, port 1025, tanpa TLS hanya di jaringan Docker lokal. Lihat pesan di `http://localhost:18025`. Worker mengirim outbox; Beat menjalankan siklus setiap 30 detik. Register/Forgot password tidak menampilkan OTP pada halaman atau log aplikasi.

Untuk inbox nyata, isi `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, TLS/SSL sesuai penyedia, dan `DEFAULT_FROM_EMAIL` dari domain yang sah. Pilih salah satu TLS atau SSL sesuai panduan SMTP. Verifikasi pengirim/domain serta SPF/DKIM/DMARC sesuai penyedia Anda. Contoh konfigurasi SMTP yang umum menggunakan port 587 + TLS; ikuti ketentuan layanan yang digunakan.

Sesudah mengubah `.env`, recreate web, worker, dan beat. Uji Register dengan email yang Anda kuasai, lalu Forgot password. Periksa inbox/spam dan log notifikasi. Kredensial tidak dikirim ke frontend. Resend OTP menerbitkan challenge baru dan membatalkan kode lama.

SMTP tidak menjamin exactly-once. Jika hasil pengiriman tidak pasti, event menjadi `UNKNOWN`. Periksa provider sebelum melakukan tindak lanjut. Pengguna dapat meminta OTP baru setelah jeda; kode lama akan tidak berlaku.

## Midtrans

- Lokal tanpa akun provider: `PAYMENT_MODE=mock`. Tombol simulasi hanya aktif di mode local dan dicap sebagai simulasi.
- Sandbox: `PAYMENT_MODE=midtrans_sandbox`, isi **Sandbox** server/client key.
- Live: `PAYMENT_MODE=midtrans_live`, isi **Production** key sesudah merchant diaktifkan. Jangan mencampur key Sandbox dan Production.

Backend membuat Snap transaction dan menyimpan redirect URL yang dibatasi ke host Midtrans. Frontend tidak dapat menandai invoice lunas. Callback asli mengarah ke `/webhooks/midtrans/`. Signature dihitung dari string `order_id + status_code + gross_amount + server_key`, dibandingkan constant-time, lalu diverifikasi lagi melalui authenticated GET status.

Atur Finish Redirect URL merchant ke `APP_URL/pembayaran/kembali/`. Sesi Snap baru juga mengirim callbacks.finish/error dengan referensi order dari backend. Parameter URL tidak dapat melunasi tagihan. Panduan lengkap: [INTEGRASI_LOCAL_PRODUCTION.md](INTEGRASI_LOCAL_PRODUCTION.md).

Webhook memerlukan endpoint HTTPS publik. Untuk localhost, gunakan tunnel pengembangan yang Anda konfigurasikan, tambahkan hostname tepat ke `ALLOWED_HOSTS`, lalu arahkan notification URL Midtrans ke tunnel tersebut. Jangan mempublikasikan seluruh debug app sebagai konfigurasi production. Bila belum memakai tunnel, tombol **Periksa ke Midtrans** dan worker melakukan GET status dari backend; ini membantu pengujian lokal tetapi tetap uji webhook sebelum go-live.

Sukses: `settlement` atau `capture` dengan fraud status yang diterima. Pending/challenge/gagal tidak membuka layanan. Nominal dan mata uang diperiksa terhadap invoice. Dana sah setelah hold berakhir tetap dicatat, lalu ditangani admin. Dana kedua dengan transaction ID berbeda disimpan sebagai unapplied, bukan dibuang.

Refund pada versi ini adalah workflow operasional dengan persetujuan Super Admin dan referensi rekonsiliasi. Operator mengeksekusi pengembalian melalui bank/provider secara terpisah. Tidak ada transfer otomatis dari tombol approve.

Referensi: <https://docs.midtrans.com/reference/backend-integration>, <https://docs.midtrans.com/docs/https-notification-webhooks>, <https://docs.midtrans.com/reference/get-transaction-status>.

## Google Login

Buat OAuth client **Web application**, isi `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, dan `APP_URL`. Daftarkan redirect URI **persis** `http://localhost:18000/auth/google/callback/` untuk lokal, atau URI HTTPS lingkungan Anda. URL `localhost` dan `127.0.0.1` berbeda; pilih satu dan daftarkan sesuai penggunaan.

Authlib memproses OIDC state/nonce dan token. Google `sub` menjadi identitas. Signup Google pertama tetap memverifikasi email melalui OTP Sinau Satwa. Untuk email yang sudah terdaftar, Login akun lokal dahulu lalu tautkan Google di Keamanan akun dengan konfirmasi password. Tidak ada auto-link atau promosi ke peran staf berdasarkan email.

Google-only user dapat menggunakan Forgot password untuk menyiapkan password setelah OTP email. Pengaturan MFA juga memerlukan pembuktian password akun.

Referensi: <https://developers.google.com/identity/openid-connect/openid-connect>, <https://developers.google.com/identity/gsi/web/guides/verify-google-id-token>.

## Maps dan jarak rute (tanpa billing Google)

Leaflet/OpenStreetMap menampilkan peta tanpa key Google. Perhitungan rute menggunakan `ROUTES_MODE=openrouteservice`, key Standard gratis di `ORS_API_KEY`, dan `ORS_BASE_URL=https://api.heigit.org`. Key hanya dikirim dari backend. Cache dan pembatas permintaan menjaga penggunaan kuota.

Rute gagal atau kuota habis tidak diganti jarak garis lurus atau fixture. Kurir Toko hanya ditawarkan setelah jarak rute tervalidasi, kapasitas dan ukuran paket sesuai. Google Login tetap terpisah. Panduan instalasi, batas layanan gratis dan UAT: [PETA_GRATIS.md](PETA_GRATIS.md).

## Biteship dan Kurir Toko

`SHIPPING_MODE=mock` menyediakan tarif instan contoh. Untuk API, gunakan `SHIPPING_MODE=biteship`, isi key Testing dari dashboard Biteship, data asal/kontak yang valid, serta pasangan webhook header bila dipakai. Quote memilih layanan instan nyata dari respons `POST /v1/rates/couriers`, dengan kode `gojek`/`grab` dan `instant`.

Alamat tujuan beserta paket disnapshot. Quote mempunyai fingerprint, versi kebijakan, dan expiry. Checkout memeriksa semuanya lagi. Kuota Kurir Toko dipegang di `DeliveryReservation`; status fulfilled tetap dihitung sebagai pemakaian jatah window. Aktifkan window ketika petugas memang tersedia. Izin `can_deliver` terpisah dari peran utama karyawan.

Shipment dibuat setelah pembayaran dan pengemasan. `reference_id` tetap untuk satu upaya. Timeout menjadi `UNKNOWN`; tidak membuat shipment baru. Rekonsiliasi memakai reference dan payload yang sama. Error duplikat Biteship `40002060` dapat memberikan `details.order_id`; backend mengambil order itu dan memeriksa reference. Bila penyedia tetap ambigu, perlu penanganan operator.

Webhook: dashboard Biteship mendukung **Headers Signature Key** dan **Headers Signature Secret**. Isi nama header dan nilai yang sama pada `BITESHIP_WEBHOOK_HEADER` serta `BITESHIP_WEBHOOK_SECRET`. Ini pasangan header yang dikonfigurasi, bukan asumsi algoritme HMAC. Backend melakukan authenticated GET sebelum menerapkan status. Endpoint: `/webhooks/biteship/`. Worker juga melakukan polling untuk kiriman yang sudah memiliki ID penyedia.

Tarif dispatch instan diperiksa lagi. Selisih ditahan dan memerlukan persetujuan biaya toko yang tercatat; nominal yang telah dibayar pelanggan tidak diubah diam-diam. Pembatalan kurir tidak membatalkan invoice/pesanan otomatis.

Kurir Toko: Admin membuat shipment internal dan menugaskan karyawan berizin; petugas membuka tugas miliknya, menandai mulai antar, kemudian mencatat nama penerima serta bukti serah terima. Hanya setelah bukti selesai pesanan menjadi completed.

Referensi: <https://biteship.com/en/docs/api/authentication>, <https://biteship.com/en/docs/api/rates/retrieve>, <https://biteship.com/en/docs/api/orders/create>, <https://biteship.com/en/docs/api/orders/retrieve>, <https://help.biteship.com/hc/en-us/articles/58382023618329-Complete-Guide-to-Understanding-Biteship-Webhooks>.
