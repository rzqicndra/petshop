# Referensi dan keputusan desain

Referensi ditinjau dari halaman resmi, bukan disalin sebagai template atau aset merek:

- Chewy: https://www.chewy.com/ — struktur navigasi menurut hewan, pencarian, dan identitas keranjang yang jelas.
- Pets at Home: https://www.petsathome.com/ — pengelompokan kebutuhan hewan, akses akun/basket, serta hubungan belanja dan layanan.
- Shopee Indonesia: https://shopee.co.id/ — pola pencarian produk dan informasi harga yang familier. Susunan alamat, ringkasan checkout, serta aksi edit/hapus pada Sinau Satwa merupakan adaptasi kebutuhan proyek, bukan klaim menyalin layar akun Shopee yang memerlukan Login.

Keputusan implementasi Sinau Satwa:

1. Pelanggan fokus pada hewan, booking, belanja, alamat, kontak, dan keamanan. Staf fokus pada antrean layanan, pengiriman, persediaan, dan pencatatan. Super Admin memiliki pengelolaan seluruh akun dan akses.
2. Warna hijau gelap untuk navigasi dan aksi utama; sage untuk latar pendukung; putih untuk area kerja. Amber menandai menunggu tindakan, merah untuk aksi berisiko/status bermasalah. Identitas Google dan WhatsApp memakai ikon yang dikenali.
3. Heading operasional memakai sans serif ringkas. Serif dibatasi pada halaman pengenalan dan kampanye katalog. Form dan tombol menggunakan aturan ukuran dan jarak bersama.
4. Grid katalog empat kolom pada desktop, tiga pada lebar menengah, dan dua pada ponsel. Panel transaksi menumpuk pada layar kecil. Form dua kolom menjadi satu kolom di ponsel; label tetap terlihat.
5. Animasi hanya sebagai penanda transisi ringan; tidak menghalangi fungsi tanpa JavaScript dan dinonaktifkan saat prefers-reduced-motion aktif.
6. Tidak ada review, rating, diskon, stok, atau janji pengiriman palsu. Foto, produk, kontak, harga, dan aturan layanan tetap bersumber dari data yang dikelola toko.
7. Aset produk bawaan tetap ilustrasi. Ganti dengan foto produk asli melalui pengaturan sebelum digunakan untuk penjualan nyata. File privat dan catatan transaksi lama tidak dihapus demi perubahan tampilan.

## Penyempurnaan katalog dan konten dinamis

Rilis ini meninjau kembali Chewy (https://www.chewy.com/) dan daftar produk Pets at Home (https://www.petsathome.com/product/listing/all-products): pencarian yang terlihat jelas, kategori hewan, basket, dan kelompok produk. Implementasi Sinau Satwa menggunakan sidebar kategori pada desktop, chip pada ponsel, sorting, detail varian dan keranjang. Konten bisnis dan foto dikelola dari dashboard. Workspace staf memakai sidebar terang dan fokus antrean/pekerjaan; pelanggan memakai identitas hijau. Grid katalog tiga kolom di desktop biasa, empat pada layar sangat lebar, dua pada ponsel.
