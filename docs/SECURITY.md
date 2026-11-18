# Keamanan dan operasional

## Perlindungan yang diterapkan

- Password melalui hasher Django, Argon2 menjadi pilihan utama. Minimum password 12 karakter dan validator umum aktif.
- OTP enam digit, lima menit, satu kali pakai, maksimal lima percobaan. Resend minimal 60 detik; email target dan purpose diikat ke challenge.
- Rate limit berbasis PostgreSQL untuk IP/email sehingga berlaku lintas proses. Header `X-Forwarded-For` tidak dipercaya secara otomatis.
- Session server-side, rotasi Login, safe redirect, pencabutan sesi setelah reset password/perubahan peran, CSRF untuk mutasi web, Logout POST.
- Tujuh peran bisnis melalui Group; role tidak diambil dari URL atau field Register. Workspace Owner menolak mutasi transaksi.
- Object authorization untuk data pelanggan, dokter/groomer/petugas yang ditugaskan, serta file privat. UUID bukan pengganti pemeriksaan izin.
- Login Google memakai OIDC authorization code, validasi library Authlib, state dan nonce. Identitas menggunakan `sub`; email sama tidak menautkan akun atau memberikan peran staf otomatis.
- MFA TOTP dengan secret terenkripsi, pencegahan replay, dan kode pemulihan sekali pakai. Wajib untuk staf pada mode production.
- Unggahan dibatasi 5 MB. Foto didekode dan ditulis ulang ke JPEG tanpa EXIF. PDF diparse, dibatasi jumlah halaman, menolak dokumen aktif tertentu, serta ditulis ulang tanpa anotasi/formulir. Ini validasi/sanitasi, bukan klaim pemindaian antivirus.
- File tidak disajikan oleh URL media terbuka. Download memerlukan otorisasi objek; gambar produk publik memiliki jalur terpisah dengan klasifikasi yang diperiksa.
- Webhook Midtrans memeriksa SHA-512 lalu GET status terautentikasi; webhook Biteship memeriksa pasangan header rahasia yang dikonfigurasi, lalu GET data penyedia.
- Harga dihitung server. Unique constraints, row locks, advisory transaction lock, dan GiST exclusions menjaga idempotensi serta kapasitas.
- Audit append only dan isi rekam medis terbit dilindungi trigger PostgreSQL. Revisi membuat versi baru.
- Header keamanan, CSP, `nosniff`, pembatasan frame, private cache policy. HTTPS/cookie secure/HSTS aktif di production.
- `.env`, upload, data, log, virtualenv dan hasil build tidak masuk Git/ZIP distribusi. Aplikasi web Docker memakai user non-root dan `no-new-privileges`.

## Sebelum production

1. Gunakan database/Redis/storage terpisah dari data demo. Jalankan dengan user database aplikasi yang tidak superuser; instal extension dan migrasi melalui akun migrasi yang terkontrol.
2. Tetapkan `DEPLOYMENT_MODE=production`, hostname, `APP_URL` HTTPS, CSRF origins yang benar, secret acak baru, dan kunci enkripsi terjaga. Mode mock ditolak di luar local.
3. Atur TLS/reverse proxy yang dipercaya, batas body, timeouts, serta konfigurasi IP asli yang tidak dapat dipalsukan. Jangan menyalin wildcard host atau mempercayai semua forwarded headers.
4. Aktifkan SMTP nyata dengan TLS dan domain pengirim terverifikasi. Terapkan kredensial provider yang dibatasi dan rotasi kunci; pisahkan key browser Maps dari key server.
5. Pastikan MFA staf selesai. Simpan recovery codes secara aman. Jangan membuat akun staf bersama atau membagikan password Super Admin.
6. Siapkan backup PostgreSQL **dan berkas privat** beserta kunci enkripsi yang diperlukan; uji restore di lingkungan terpisah. Tetapkan jadwal, akses backup, retensi, dan prosedur pemulihan bersama pemilik usaha.
7. Tentukan retensi data, permintaan koreksi/penghapusan, persetujuan pemilik hewan, kebijakan refund, kontak resmi, serta penanggung jawab operasional. Naskah privasi saat ini adalah draft peninjauan.
8. Tambahkan pemindaian malware jika diperlukan untuk dokumen nyata, observabilitas, alert anomali pembayaran, dan monitoring antrean `UNKNOWN`/`FAILED`.
9. Jalankan tes di konfigurasi deployment, lakukan UAT per peran dan uji perangkat ponsel nyata. Audit dependensi dan update patch secara rutin.

Tidak ada klaim kebal serangan atau siap production hanya berdasarkan test suite. Pengujian integrasi provider nyata, konfigurasi infrastruktur, dan penerimaan client tetap diperlukan.

## Pelaporan masalah

Catat waktu, URL tanpa token, role, langkah reproduksi, serta `X-Request-ID`. Gunicorn memakai format log path tanpa query; atur reverse proxy agar tidak mencatat query callback OAuth atau undangan. Jangan memasukkan password, OTP, server key, rekam medis, atau data pelanggan nyata ke issue GitHub publik.


Panduan pembaruan audit dan rotasi yang masih perlu dilakukan: [PERBAIKAN_AUDIT_QA.md](PERBAIKAN_AUDIT_QA.md).
