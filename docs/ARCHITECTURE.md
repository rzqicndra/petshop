# Arsitektur implementasi

## Batas sistem

Modular monolith untuk satu lokasi: Django mengelola halaman dan aturan bisnis; PostgreSQL menjadi sumber kebenaran transaksi; Celery/Redis menjalankan pekerjaan latar. Satu domain dan satu portal Login cukup. Tidak ada modul cabang, microservices, atau aplikasi mobile pada versi ini.

## Lapisan kode

- `models.py`: tipe data, relasi, indeks, unique/check/exclusion constraints.
- `forms.py`: validasi input, pilihan FK yang dibatasi pengguna, dan pesan isian.
- `services.py`: pemeriksaan peran, transisi status, perhitungan server, transaksi, audit, dan outbox.
- `providers.py`: HTTP Midtrans/Google Routes/Biteship, timeout, pemetaan respons.
- `views.py`: memuat objek sesuai akses, memanggil service, lalu merender atau redirect.
- `core/selectors.py`: pembatasan objek Booking dan pesanan berdasarkan pelanggan/penugasan.
- `core/files.py`: validasi dan sanitasi unggahan, storage privat, serta otorisasi download.

Templates dan JavaScript membantu interaksi. Keduanya tidak menentukan nominal tagihan, peran, stok, kapasitas, status lunas, atau kelayakan ulasan.

## Model dan transaksi

Entitas memakai UUID, timestamps, rupiah integer, waktu berzona, dan FK eksplisit. Snapshot item/alamat/harga menjaga riwayat saat master berubah. Customer dapat belum memiliki User untuk transaksi datang langsung. Nama dan telepon tidak menjadi kunci penggabungan akun.

`Booking.status` merupakan satu status operasional untuk dokter, grooming, dan penitipan. `Visit`, `GroomingJob`, dan `BoardingStay` menyimpan rincian pelaksanaan tanpa status operasional duplikat. Pembayaran, pengiriman, dan refund memiliki status terpisah.

Mutasi commerce memperoleh PostgreSQL transaction advisory lock untuk satu toko, dilanjutkan row lock yang diperlukan. Pilihan ini sengaja sederhana untuk volume satu lokasi: membuat urutan expiry, alokasi, pembayaran dan perpanjangan konsisten lintas web/worker. Tidak ada HTTP provider di dalam pengunci ini. Jika volume meningkat, pisahkan pengunci per domain dengan urutan yang teruji; jangan menghapus pengunci tanpa uji paralel.

Database tetap menolak saldo tidak valid, slot bertabrakan, target invoice ambigu, payment diterapkan dua kali, serta beberapa shipment aktif untuk pesanan yang sama. Exclusion constraint menggunakan `btree_gist` dan rentang setengah terbuka `[mulai, selesai)`. Buffer/pembersihan dimasukkan ke rentang resource.

## Outbox

Perubahan bisnis dan event outbox disimpan pada commit yang sama. Worker mengirim notifikasi di luar transaksi. OTP disimpan sebagai digest untuk verifikasi; salinan sementara untuk pengiriman dienkripsi, diberi masa berlaku, dan dihapus setelah selesai/kedaluwarsa. Hasil SMTP yang ambigu menjadi `UNKNOWN`, tidak dikirim ulang secara buta.

Reminder menyimpan versi sumber. Perubahan jadwal atau revisi medis membatalkan reminder lama. Email pengingat mengarahkan pengguna ke Dashboard untuk melihat data terkini, tanpa menyalin diagnosis atau catatan internal.

## Data master dan antarmuka

Management Django membatasi edit ke data master. Transaksi, saldo stok, pembayaran, audit, dan rekam medis tidak dapat diubah melalui formulir generik. Produk mendukung unggahan foto tersanitasi; hanya file dengan klasifikasi publik yang disetujui dapat dilihat anonim.

CSS menggunakan token warna: forest untuk aksi utama/kepercayaan, paper untuk ruang baca, clay untuk aksen, sage untuk konteks tenang, honey untuk perhatian. Warna status selalu disertai teks. Font dan aset tersedia lokal; tidak memerlukan CDN untuk halaman utama.
