# Pembaruan katalog, konten, dan workspace Sinau Satwa

Paket ini melanjutkan rilis UI/UX dan audit sebelumnya. Pemasangan memperbarui source dan menambah struktur data. Database transaksi, berkas privat, dan konfigurasi `.env` yang sudah Anda gunakan dipertahankan. Website di laptop belum berubah sebelum update dipasang.

## Pengelolaan dari dashboard

| Bagian | Tempat mengelola | Dampak perubahan |
| --- | --- | --- |
| Logo, nama usaha, tagline, footer, teks tombol CS | Data master → Profil toko | Header, sidebar, footer, halaman akun; nama/tagline/footer juga pada email OTP HTML |
| Alamat, titik toko, kontak CS, jam operasional | Data master → Profil toko | Kontak publik, lokasi, dan asal pengiriman sesuai pengesahan data toko |
| Teks pembuka dan gambar beranda | Data master → Konten website → Beranda · pembuka | Judul, label, isi, foto, deskripsi foto, tombol dan tujuan tombol |
| Bagian layanan, perawatan, produk pada beranda | Data master → Konten website | Judul/isi dan status tampil masing-masing bagian |
| Pembuka katalog | Data master → Konten website → Katalog · pembuka | Teks dan foto banner katalog |
| Visual Login/Register/OTP/reset | Data master → Konten website → Login & Register · visual | Foto, judul, isi dan label. Nonaktifkan untuk tampilan form tanpa visual |
| Pembuka layanan, kontak, ulasan | Data master → Konten website | Teks pengantar halaman yang bersangkutan |
| Privasi & ketentuan | Data master → Konten website | Isi kebijakan dalam teks biasa, tampil dengan paragraf |
| Jenis hewan dan foto kategori hewan | Data master → Jenis hewan | Pilihan booking, profil hewan, dan pintasan katalog |
| Kategori dan gambarnya | Data master → Kategori produk | Pengelompokan katalog sesuai hewan yang dipilih |
| Produk, foto, harga, ukuran, sasaran hewan, stok awal | Data master → Produk | Produk dan varian dibuat bersama; langsung dapat tampil di katalog |
| Varian tambahan | Data master → Varian & harga | Pilihan ukuran/harga/foto tambahan pada detail produk |
| Stok lanjutan | Persediaan | Mutasi stok tercatat; tidak mengubah jumlah stok melalui form produk |
| Nama, deskripsi, foto layanan | Data master → Layanan | Kartu layanan pada beranda dan halaman layanan |
| Harga/durasi layanan, jadwal, fasilitas, penitipan, pengiriman | Bagian terkait di Data master | Data operasional mengikuti validasi dan hak akses yang sudah ada |
| Akun pelanggan/staf dan peran | Pengguna & akses, khusus Super Admin | Pengaturan akun dan pencabutan sesi mengikuti aturan keamanan sebelumnya |

Teks dan data bisnis dikelola melalui form. Struktur halaman, identitas tombol Google/WhatsApp, hak akses, serta aturan pembayaran tetap dijaga aplikasi agar perubahan konten tidak mengubah keamanan. Field konten menerima teks biasa, bukan kode HTML/JavaScript. Tujuan tombol dipilih dari halaman internal yang diizinkan.

## Produk yang sebelumnya tidak muncul

Halaman katalog menjual **varian**, karena harga, SKU, berat dan ukuran ada pada varian. Form lama hanya menambahkan nama produk. Rilis ini menyatukan langkah tersebut.

1. Buka Data master → Produk.
2. Edit produk lama yang belum muncul, atau tambah produk baru.
3. Isi kategori, SKU, nama varian/ukuran, harga, berat, dan dimensi paket sebenarnya.
4. Pilih jenis hewan yang sesuai. Kosongkan untuk produk universal; produk ini tampil pada semua hewan.
5. Unggah foto JPG, PNG atau WebP. Metadata dibuang dan gambar dinormalisasi di server. Maksimal 5 MB.
6. Aktifkan produk dan varian. Kategorinya juga harus aktif.
7. Stok awal hanya untuk varian baru. Untuk makanan dengan batas penggunaan, isi tanggal stok awal. Setelah tersimpan, gunakan Persediaan untuk penerimaan atau penyesuaian berikutnya.
8. Simpan dan buka katalog. Daftar admin menampilkan `Tayang di katalog`, `Draft · produk nonaktif`, `Kategori nonaktif`, atau `Lengkapi varian & harga`.

Produk tanpa stok tetap tampil dengan `Stok habis` dan tombol tambah nonaktif. Sistem tidak membuat stok atau harga fiktif. Produk lama tanpa varian dipertahankan dan perlu dilengkapi melalui editor; tidak diberi harga otomatis. Editor Produk menampilkan varian aktif pertama; gunakan Varian & harga untuk mengatur varian tambahan.

## Perubahan pengalaman pengguna

- Katalog memiliki banner yang dapat dikelola, pintasan hewan, kategori, pencarian, urutan harga/nama/terbaru, detail produk dan pilihan varian.
- Keranjang tetap menerima penambahan tanpa berpindah ke checkout. Filter dan urutan dipertahankan pada pagination. Kategori mengikuti hewan yang dipilih.
- Dashboard staf berfokus pada pekerjaan, metrik, jadwal, pesanan dan pintasan operasional, dengan sidebar terang. Pelanggan memakai navigasi hijau dan alur perawatan/belanja.
- Dropdown memakai komponen custom berwarna sage, mendukung keyboard, Escape, pilihan tunggal/multiple, pencarian untuk daftar panjang, nilai form asli, dan fallback native bila JavaScript tidak berjalan. Pemilih tanggal/file tetap memakai fasilitas perangkat agar mudah digunakan.
- Tombol Google memiliki ikon dan teks satu kelompok di tengah. WhatsApp memiliki kotak ikon tetap; pada ponsel, label disembunyikan dan ikon tetap terlihat.
- Kontak darurat dapat dihapus dengan konfirmasi. Penghapusan mengarsipkan kontak agar tidak tersedia untuk booking baru; snapshot kontak pada penitipan sebelumnya tetap tersimpan.
- Foto/logo tidak dibuat publik hanya karena berhasil diunggah: endpoint publik memeriksa klasifikasi, validasi, serta referensi data aktif. Dokumen kesehatan tetap privat.
- Edit/hapus hewan dan alamat, revisi dokumen, pemisahan tindakan staf/pelanggan, pembatasan tagihan tertutup, email OTP HTML dan keamanan dari rilis sebelumnya dipertahankan.

## Cara memasang — Windows CMD

### 1. Folder paket

Unduh ZIP terbaru. Setelah ekstrak, cari **folder yang langsung berisi `manage.py`, `scripts`, `templates`, dan `static`**. Beri nama folder itu `sinau-satwa-dinamis`, letakkan di `C:\Users\Rizqi`.

Pastikan installer ditemukan:

```bat
dir "C:\Users\Rizqi\sinau-satwa-dinamis\scripts\install_update.py"
```

Folder `C:\Users\Rizqi\sinau-satwa` tetap proyek utama yang dijalankan. Jangan mengganti atau menghapus folder utama dan `.env`-nya.

### 2. Hentikan aplikasi dan backup

Semua perintah berikut dijalankan dari proyek utama. Hentikan ngrok dahulu dengan Ctrl+C di terminal ngrok.

```bat
cd /d C:\Users\Rizqi\sinau-satwa
docker compose stop web worker beat
docker compose up -d --wait db
mkdir var\dynamic-update-backup
copy .env var\dynamic-update-backup\environment-backup.txt
docker compose exec -T db pg_dump -U sinau -d sinau --no-owner --no-acl > var\dynamic-update-backup\before-dynamic.sql
docker compose cp web:/app/var/private var\dynamic-update-backup\private
```

Gunakan folder backup baru bila nama tersebut sudah ada. Sesuaikan user/database apabila diubah. Pastikan SQL tidak kosong, salinan environment ada, dan berkas privat berhasil disalin. Berhenti bila backup gagal. Simpan backup secara privat.

### 3. Periksa dan jalankan installer

```bat
py "C:\Users\Rizqi\sinau-satwa-dinamis\scripts\install_update.py" --target "C:\Users\Rizqi\sinau-satwa" --dry-run
```

Jika tidak ada error, jalankan:

```bat
py "C:\Users\Rizqi\sinau-satwa-dinamis\scripts\install_update.py" --target "C:\Users\Rizqi\sinau-satwa"
```

Installer menyimpan source lama yang diganti ke `var/update-backups`. Jika ada perubahan source yang Anda buat sendiri, bandingkan terlebih dahulu. Konfigurasi integrasi yang sudah dipilih dipertahankan.

### 4. Build, migrasi, dan jalankan

```bat
docker compose build web worker beat
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose up -d --force-recreate --wait web worker beat
docker compose exec web python manage.py check
docker compose exec web python manage.py check_integrations --strict
docker compose ps
```

Migrasi menambah pengaturan merek, tabel konten, gambar kategori/hewan/layanan, dan penanda arsip kontak. Konten awal dibuat satu kali agar halaman lama tetap terisi. Migrasi tidak menghapus transaksi, mengatur ulang pengguna, atau menimpa rahasia.

Jangan gunakan `docker compose down -v` atau `seed_demo` pada proyek berisi data Anda.

### 5. Buka dan uji

Buka `http://localhost:18000`, tekan **Ctrl+F5**. Login sebagai Super Admin atau Admin untuk pengelolaan; Owner tetap akses lihat. Aktifkan kembali ngrok jika memerlukan webhook.

Coba alur berikut:

1. Edit logo/tagline lalu periksa sidebar, header dan halaman Login.
2. Edit banner katalog melalui Konten website, lalu periksa akun pelanggan.
3. Lengkapi produk lama yang tidak muncul; buat produk baru beserta varian, foto dan stok awal.
4. Pilih hewan/kategori, ubah urutan harga, buka detail produk dan tambah ke keranjang.
5. Hapus kontak darurat milik pelanggan; pastikan tidak ditawarkan untuk booking baru.
6. Uji menu ponsel: tombol X, ketuk area di luar menu, dan scroll kembali.
7. Uji Google Login, email OTP asli, pembayaran sandbox/webhook dan pengiriman testing dengan konfigurasi Anda.

## Validasi dan batas pemeriksaan

165/165 tes lulus pada PostgreSQL 17.10 terpisah, termasuk 20 tes tambahan pada rilis ini. Pemeriksaan Django, migrasi, konsistensi migrasi, collectstatic dan sintaks JavaScript berhasil. Tes memakai data sintetis, bukan database laptop Anda.

Tes baru mencakup penyimpanan produk/varian/foto/stok, SKU duplikat tanpa data parsial, edit tanpa menggandakan stok, produk/kategori nonaktif, produk universal, sorting/pagination, pemisahan workspace, arsip kontak, konten yang langsung terlihat, pencegahan HTML aktif, pembatasan gambar publik, aturan tujuan tombol, hak akses dan isi installer.

Pemeriksaan browser mencakup katalog publik yang berjalan, sorting lewat keyboard dan penambahan keranjang. Tampilan peran dirender dari fixture Django tanpa memakai kredensial pelanggan/staf asli. Pemeriksaan lebar ponsel melalui zoom browser, bukan perangkat fisik, mencakup dua kolom katalog, tidak ada luapan horizontal, menu dan ikon WhatsApp. Google ditinjau tampilannya; proses autentikasi pihak ketiga tidak dijalankan.

Paket belum dipasang di laptop atau dideploy ke server Anda. Pengiriman email, pembayaran, peta/rute dan kurir nyata tidak dijalankan dalam sesi ini. Mode, kredensial dan ketersediaan jaringan tetap mengikuti `.env` serta akun provider Anda. Rahasia yang pernah dibagikan perlu diganti melalui akun terkait; paket tidak merotasinya otomatis. Untuk production gunakan konfigurasi HTTPS, MFA staf, backup, data usaha resmi, foto produk sebenarnya dan pengujian penerimaan pada perangkat yang dipakai pelanggan.
