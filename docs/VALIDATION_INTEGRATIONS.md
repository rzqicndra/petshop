# Verifikasi revisi integrasi, 16 November 2026

- Full suite: 94 tes lulus pada PostgreSQL 17.10, termasuk query reminder dan 12 tes integrasi baru.
- Dua tes tambahan installer lulus: dry run tidak menulis file, update mempertahankan secret/SMTP/.env/runtime dan membuat backup kode lama.
- Migrasi database kosong, system check, makemigrations --check, collectstatic: lulus. Tidak ada migrasi model baru.
- Pemeriksaan konfigurasi framework production check --deploy --fail-level WARNING: lulus; provider disabled untuk pemeriksaan offline, bukan deploy nyata.
- compose.yaml dan compose.production.yaml: YAML terparse; Docker daemon/build container production tidak tersedia untuk diuji dalam sesi ini.
- Sumber Python diformat dengan Black pada file revisi.
- Midtrans Snap callbacks dan override notification, URL return/legacy, kepemilikan invoice, penolakan forged settlement query, validasi origin/mode/TLS, dan diagnostic tanpa mencetak secret: diuji otomatis.
- Kredensial/API project pengguna, Google consent/Maps billing/quota, Biteship Testing/Live dan webhook publik belum diuji end-to-end dari sesi ini. Hasil TLS diagnostik tidak memvalidasi API key. Tidak ada pembayaran, pengiriman atau email internet yang dijalankan oleh agen.
- SMTP internet sudah diuji berhasil oleh pengguna pada instalasi lokal sesuai log percakapan, bukan oleh sesi pengujian ini.
- Jalankan UAT per provider sesuai INTEGRASI_LOCAL_PRODUCTION.md sebelum operasional production. Laporan VALIDATION.md merekam pengujian awal versi sebelumnya.
