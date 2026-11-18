# Pembaruan UI/UX dan alur Sinau Satwa

Paket ini melanjutkan versi perbaikan audit. Source diperbarui; website di laptop Anda belum berubah sebelum installer dijalankan. Konfigurasi .env, database, berkas privat, serta integrasi yang sudah Anda isi tidak diganti dengan data uji.

## Perubahan yang diterapkan

- Data master memakai halaman dashboard sendiri di /pengaturan/, termasuk profil toko, peta, kontak, dan form jam operasional per hari. Tautan profil toko lama tetap menuju tampilan baru. Produk, varian/harga/foto, layanan, unit, tim, jadwal, batch, dan pengiriman memakai shell yang sama. Pengguna Owner tetap hanya dapat melihat.
- Super Admin dapat mencari dan mengelola seluruh akun pelanggan serta staf. Pengaturan peran dan status akun tetap mencabut sesi lama; Super Admin aktif terakhir tidak dapat dinonaktifkan.
- Staf tidak mendapat tombol bayar online, simulasi pelanggan, atau pemeriksaan provider manual. Aksi bayar juga ditolak server bagi role staf. Pencatatan dana tunai di kasir tetap ada untuk Admin/Super Admin.
- Fitur refund di halaman transaksi dan data master dihapus. Aksi HTTP lama untuk meminta/memproses refund melalui halaman tagihan tidak dijalankan. Catatan keuangan lama dan pencatatan penyesuaian historis tetap disimpan; penghapusan tampilan tidak menghapus bukti transaksi.
- Katalog memakai pencarian, filter hewan/kategori, kartu produk, stok, dan keranjang. Tambah produk menampilkan notifikasi dan memperbarui jumlah keranjang tanpa pindah halaman. Tanpa JavaScript, pengguna tetap kembali ke katalog. Checkout tetap memerlukan Login.
- Keranjang memiliki update jumlah dan hapus item. Checkout memisahkan keranjang, cara menerima, alamat penerima, pilihan pengiriman, dan pembayaran. Alamat punya kontak, label, alamat utama, titik peta, serta opsi edit dan hapus.
- Hapus alamat menggunakan arsip: alamat pesanan lama tidak berubah. Bila alamat utama dihapus, alamat aktif lain dijadikan utama. Alamat yang diarsipkan tidak dapat dipakai untuk checkout baru.
- Hewan memiliki tombol edit dan hapus. Hapus mengarsipkan profil, bukan menghapus riwayat medis. Hewan dengan booking aktif, termasuk menunggu pembayaran, tidak dapat dihapus sebelum layanan selesai/dibatalkan.
- Dokumen kesehatan dapat diganti oleh pemilik akun dan tim operasional yang berwenang selama tahap yang diizinkan. Dokumen lama tetap tersimpan, dokumen pengganti memerlukan verifikasi ulang. Tombol verifikasi tidak muncul setelah disahkan; permintaan verifikasi ulang terhadap dokumen yang sama juga ditolak server.
- Verifikasi hanya menggunakan dokumen aktif. Check-in ditahan jika dokumen pengganti belum diverifikasi. Validasi berkas tetap maksimal 5 MB dan pemeriksaan isi foto/PDF di server.
- Form upload memakai area pilihan file yang seragam, nama/ukuran berkas, dan preview untuk gambar. Foto profil hewan menolak PDF yang disamarkan sebagai foto.
- Tagihan untuk pesanan yang dibatalkan atau melewati batas waktu tidak dapat dibuka pelanggan melalui tautan langsung. Tautannya disembunyikan. Staf tetap dapat melihat catatan tagihan historis untuk kebutuhan pencatatan, tanpa memberi pelanggan jalan pembayaran baru.
- Status tagihan aktif diperbarui otomatis dari endpoint milik aplikasi. Browser tidak menandai tagihan lunas dari parameter URL; status provider tetap diverifikasi server/background worker.
- Keamanan akun memiliki pengaturan password, koneksi Google, dan verifikasi dua langkah dengan langkah yang lebih jelas. QR autentikator dibuat di server tanpa layanan QR eksternal. Password mempunyai pilihan tampil/sembunyikan.
- Login/Register dirapikan; tombol Login rata tengah dan Google memakai ikon berwarna. Kontak CS memakai ikon WhatsApp. Email OTP register/reset password memakai HTML bermerek dengan versi teks biasa sebagai fallback.
- Menu mobile memiliki tombol tutup, backdrop, Escape, pengembalian fokus, dan penguncian scroll saat terbuka. Elemen menu yang tertutup tidak ikut fokus. Layout katalog, form, tabel, dan panel menyesuaikan breakpoint ponsel/tablet/desktop.
- Tipografi, ukuran panel, jarak, ikon, dan tombol disatukan. Animasi masuk/scroll digunakan secara ringan pada halaman publik serta menghormati preferensi reduced motion. Banner lingkungan pengembangan dan istilah provider pembayaran tidak ditampilkan pada antarmuka produk.

## Cara memasang di Windows CMD

### 1. Siapkan folder paket terpisah

Unduh ZIP terbaru. Cari folder hasil ekstrak yang berisi manage.py, scripts, templates, dan static. Beri nama folder tersebut sinau-satwa-ui, lalu letakkan di C:\Users\Rizqi.

Pastikan file ini ada:

```bat
dir "C:\Users\Rizqi\sinau-satwa-ui\scripts\install_update.py"
```

Jika tidak ditemukan, cari lokasi sebenarnya:

```bat
where /r C:\Users\Rizqi install_update.py
```

Gunakan installer dari paket UI terbaru, bukan installer di folder proyek utama atau paket perbaikan lama.

### 2. Semua perintah tetap dijalankan dari proyek utama

```bat
cd /d C:\Users\Rizqi\sinau-satwa
```

Hentikan ngrok dengan Ctrl+C, kemudian:

```bat
docker compose stop web worker beat
docker compose up -d --wait db
```

### 3. Backup sebelum perubahan

Gunakan folder backup baru; jangan menimpa backup sebelumnya.

```bat
mkdir var\ui-update-backup
copy .env var\ui-update-backup\environment-backup.txt
docker compose exec -T db pg_dump -U sinau -d sinau --no-owner --no-acl > var\ui-update-backup\before-ui-update.sql
docker compose cp web:/app/var/private var\ui-update-backup\private
```

Sesuaikan user/database bila Anda mengganti nama sinau. Periksa setiap perintah berhasil, file SQL tidak kosong, dan berkas privat tersalin. Jangan lanjut bila backup gagal. Backup berisi data dan secret; simpan privat dan jangan unggah ke GitHub/chat.

### 4. Periksa dan pasang pembaruan

```bat
py "C:\Users\Rizqi\sinau-satwa-ui\scripts\install_update.py" --target "C:\Users\Rizqi\sinau-satwa" --dry-run
```

Jika daftar perubahan sesuai dan tidak ada error:

```bat
py "C:\Users\Rizqi\sinau-satwa-ui\scripts\install_update.py" --target "C:\Users\Rizqi\sinau-satwa"
```

Installer menyimpan salinan source lama yang diganti ke var/update-backups. Jika Anda mengubah source sendiri, bandingkan perbedaannya terlebih dahulu. Jangan menimpa .env lama dengan file contoh.

### 5. Build dan migrasi

```bat
docker compose build web worker beat
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose up -d --force-recreate --wait web worker beat
```

Migrasi baru menambahkan penanda arsip alamat dan dokumen. Data lama tetap aktif. Tidak ada tabel/kolom lama yang dihapus. Jika migrasi gagal, berhenti dan periksa error sebelum menyalakan layanan.

Jangan menjalankan docker compose down -v atau seed_demo pada instalasi berisi data Anda.

### 6. Verifikasi

```bat
docker compose ps
docker compose exec web python manage.py check
docker compose exec web python manage.py check_integrations --strict
```

Buka http://localhost:18000. Tekan Ctrl+F5 agar browser mengambil CSS/JavaScript terbaru. Jalankan ngrok kembali bila diperlukan untuk webhook.

Masuk sebagai Super Admin/Admin dan gunakan menu Data master, kemudian Profil toko. Kontak dan jam operasional resmi tetap perlu diisi sesuai usaha. Gunakan foto produk asli melalui Varian & harga agar katalog tidak memakai ilustrasi produk bawaan.

### 7. Uji dengan akun pelanggan dan staf

- Tambah dua produk: tetap di katalog, jumlah keranjang bertambah, update/hapus item di keranjang bekerja.
- Checkout pickup dan delivery: alamat, kontak, ongkir, serta total sesuai.
- Edit/hapus hewan dan alamat: tidak mengubah data akun lain atau riwayat pesanan.
- Ganti dokumen: versi baru menunggu verifikasi, versi lama tetap tersimpan, tombol verifikasi hilang setelah pengesahan.
- Periksa mobile: buka/tutup menu, klik di luar menu, scroll, filter katalog, isi form, dan unggah file.
- Coba Login Google, OTP register/reset melalui email asli, pembayaran sandbox beserta webhook, pengiriman testing, dan rute pada akun provider Anda.

## Catatan validasi

145/145 tes lulus pada PostgreSQL 17 terpisah, termasuk 23 tes tambahan pada rilis ini. Django check, migrasi, pemeriksaan konsistensi migrasi, collectstatic, dan pemeriksaan sintaks JavaScript berhasil. check --deploy --fail-level WARNING lulus pada konfigurasi produksi uji; ini bukan verifikasi hosting/provider nyata.

Pengujian backend memakai PostgreSQL 17 terpisah dan data sintetis. Endpoint bisnis, hak akses, arsip data, perubahan dokumen, rendering master, HTML email, polling tagihan, dan alur lama diperiksa melalui suite regresi. Rincian jumlah tes dan output ada pada paket hasil pengujian.

Pemeriksaan browser mencakup halaman publik yang berjalan serta tampilan peran yang dirender dari fixture melalui Django. Penambahan keranjang diuji pada halaman publik yang benar-benar berjalan. Tampilan role diperiksa dari salinan HTML data uji; tidak menggunakan password/session pelanggan asli. Breakpoint tablet dan ponsel diperiksa melalui zoom browser (sekitar 681 dan 340 CSS px), termasuk menu tutup/backdrop/Escape. Ini tidak menggantikan uji perangkat HP/tablet fisik dan email client asli.

Kredensial tidak dibuat ulang oleh paket ini. Rotasi secret yang pernah dibagikan pada percakapan masih harus diselesaikan di akun provider. Menghilangkan banner pengembangan tidak mengubah mode sandbox menjadi transaksi nyata atau mengganti konfigurasi produksi. Sebelum rilis, gunakan domain HTTPS, setting production, database terpisah dari uji, backup teruji, serta kredensial dan data usaha resmi.
