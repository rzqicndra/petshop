# Pengujian dan batas verifikasi

## Cara menjalankan ulang

Gunakan PostgreSQL, bukan SQLite, karena GiST exclusion, range, trigger, dan penguncian transaksi merupakan bagian aturan aplikasi.

```powershell
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py test tests --noinput -v 2
```

Tes membuat database terpisah. Akun database pengujian harus diizinkan membuat test database. `compose.yaml` memakai PostgreSQL 17. Hasil sesi pembangunan dicatat dalam `VALIDATION.md` sesudah verifikasi akhir.

## Cakupan otomatis

- Register hanya Customer, email OTP, hash/purpose/single-use/expiry, batas percobaan, resend, target email, Forgot password, pencabutan sesi.
- Login per role setelah password benar, open redirect, CSRF, Logout POST, Owner read-only, workspace yang tidak dimiliki, MFA TOTP dan recovery sekali pakai.
- Google email sama tidak otomatis menautkan akun staf. Undangan staf memerlukan OTP serta pengaturan password. Super Admin terakhir dijaga.
- Private media, IDOR Booking/invoice/PDF, draft medis tersembunyi, catatan internal tidak masuk PDF, revisi baru, trigger rekam medis dan audit immutable.
- Stok per batch, FEFO, stok terakhir, expiry, harga/keranjang berubah, Checkout, pembayaran idempoten, dana ganda, dana terlambat, refund terbatasi, serah terima.
- Booking resource dan hewan tidak bentrok, reschedule dengan versi, dokumen penitipan, approve/reject, cleaning buffer, perpanjangan hanya aktif setelah pembayaran, tambahan yang kedaluwarsa tidak membatalkan periode awal.
- Filter spesies/kategori, data master, halaman seluruh role, header keamanan, dan tidak ada jalur media terbuka.
- Pilihan kurir dekat/jauh, kegagalan rute, fingerprint dan expiry quote, kuota termasuk fulfilled, shipment UNKNOWN tanpa duplikasi, selisih biaya yang membutuhkan persetujuan, dan bukti internal.
- Kontrak HTTP/signature/provider melalui mock terkontrol. Hasil SMTP ambigu tidak dikirim ulang tanpa kepastian.

Empat tes transaksi memakai koneksi PostgreSQL terpisah secara paralel: stok terakhir, dokter, callback pembayaran duplikat, dan kuota window pengiriman.

## Skenario UAT client

1. Buat akun dengan email yang Anda kuasai. Uji kode benar/salah/kedaluwarsa, resend, Login dan Forgot password.
2. Tambahkan hewan, kontak darurat, dan alamat/pin. Pastikan kategori katalog mengikuti jenis hewan.
3. Booking grooming; bayar; Login Groomer untuk mulai dan isi hasil; lakukan serah terima; tulis ulasan dari Customer. Ulasan sebelum selesai harus ditolak.
4. Booking dokter; terbitkan hasil/panduan/lampiran serta kontrol. Customer mengunduh PDF. Revisi dokter harus menjadi versi baru dan catatan internal tidak tampil.
5. Ajukan penitipan; unggah dokumen. Admin memverifikasi, memilih unit/petugas, menyetujui atau menolak. Sesudah lunas, check-in dapat dilakukan mulai 30 menit sebelum jadwal.
6. Saat sedang menginap, ajukan perpanjangan. Uji Tolak dengan alasan; uji Setujui, pembayaran tambahan, perubahan jadwal sekali, serta expiry tanpa mengubah jadwal awal.
7. Checkout produk dengan ambil di toko dan pengiriman. Uji kurir karyawan dan instan. Tugas karyawan harus mencatat mulai antar dan bukti penerimaan sebelum selesai.
8. Login Owner dan coba kirim aksi perubahan: server harus menolak. Customer lain tidak boleh membaca transaksi atau berkas milik Anda.
9. Jalankan dua Checkout pada stok/kuota terakhir dan dua Booking untuk jadwal yang sama. Hanya satu yang berhasil.
10. Uji koneksi provider Sandbox, duplicate webhook, callback setelah expiry, timeout, dan kegagalan email dengan akun provider milik proyek.

## Batas hasil

Mock HTTP menguji kontrak dan keputusan aplikasi, bukan persetujuan merchant, ketersediaan kurir, ketepatan rute nyata, deliverability email, atau konfigurasi Google Cloud. Semua itu perlu diuji dengan kredensial dan konfigurasi lingkungan Anda.

Docker Desktop tidak tersedia dalam lingkungan pembangunan sesi ini; image Compose dan workflow CI perlu dijalankan ulang di komputer Anda/GitHub. Pengujian database native dan pemeriksaan struktur Compose dicatat terpisah dari klaim menjalankan Docker.

Browser memeriksa halaman publik, filter katalog, keranjang tamu, dan gate Login Booking/Checkout. Halaman role dan mutasi diuji lewat Django test client dengan fixture autentikasi. Uji ponsel nyata, aksesibilitas menyeluruh, beban produksi, pentest independen, serta backup/restore production belum merupakan hasil sesi ini.
