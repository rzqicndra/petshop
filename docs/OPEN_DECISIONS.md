# Data usaha dan keputusan sebelum go-live

Persetujuan fitur sudah menjadi dasar implementasi. Berikut adalah data operasional yang masih memerlukan isi resmi; aplikasi lokal tetap dapat diuji dengan seed.

| Data / keputusan | Keadaan awal | Tempat pengaturan |
|---|---|---|
| Alamat, koordinat toko, WhatsApp CS | Tidak ditampilkan sebagai kontak resmi | StoreSettings / data master |
| Jam buka dan hari libur | Contoh 08.00–20.00 setiap hari | StoreSettings, StaffShift, blok kapasitas |
| Nama paket, harga, durasi, buffer | Contoh untuk uji | ServicePackage dan PackageResource |
| Dokter/groomer/petugas aktual | Akun demo per role | Akun & peran staf; Resource/Shift |
| Unit dan tarif penitipan | Contoh dua unit per spesies | BoardingUnit |
| Dokumen kesehatan yang diwajibkan | Ada upload dan verifikasi; jenis persyaratan final perlu disahkan | Prosedur penerimaan operasional |
| Radius dan ongkir Kurir Toko | Contoh 5 km, tarif contoh | DeliveryPolicy |
| Ketersediaan kurir, batas barang, window dan kuota | Contoh window/kuota | DeliveryPolicy, DeliveryWindow, izin karyawan |
| Produk, foto, SKU, batch dan saldo | Produk/ilustrasi contoh | Data master + persediaan |
| Domain pengirim email dan SMTP | Mailpit | `.env` dan dashboard penyedia |
| Merchant pembayaran | Simulasi lokal | `.env` dan akun Midtrans |
| Google OAuth, Maps billing/restrictions | Belum diisi | `.env` dan Google Cloud Console |
| Biteship Testing/Production | Simulasi lokal | `.env` dan dashboard Biteship |
| Pembatalan, refund, keterlambatan jemput | Workflow tersedia; angka/ketentuan final belum menjadi kebijakan hukum | Peninjauan client sebelum produksi |
| Retensi data, backup, akses medis, persetujuan pemilik | Harus ditetapkan pengelola | Dokumen kebijakan dan konfigurasi deployment |

Penambahan fitur di luar baseline dibahas sebagai perubahan ruang lingkup. Mengisi data resmi dan menjalankan UAT merupakan bagian penyelesaian lingkungan sebelum digunakan pelanggan nyata.
