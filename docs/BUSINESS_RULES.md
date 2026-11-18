# Aturan bisnis versi 1

| Area | Perilaku sistem |
|---|---|
| Login | Satu portal. Redirect berdasarkan role sah setelah autentikasi, bukan setelah mengetik email. |
| Register | Selalu akun pelanggan. Email harus terverifikasi sebelum transaksi. |
| OTP | Enam digit, lima menit, lima percobaan, resend 60 detik. OTP terikat email dan tujuan. |
| Google | Identitas `sub`; akun lama ditautkan secara eksplisit setelah pembuktian password. |
| Dashboard | Logo menuju workspace aktif. Tidak ada navigasi Kembali ke website. |
| Pelanggan datang langsung | Customer dapat tanpa User. Kasir dan Booking memakai stok/kapasitas yang sama dengan online. |
| Booking tamu | Pengguna diarahkan ke Login sebelum membuka formulir Booking. |
| Hewan | Harus milik Customer yang melakukan Booking; paket cocok dengan spesies. |
| Jadwal | Jam operasional, shift, blok libur, resource, hewan dan buffer diperiksa. Tidak ada double booking resource eksklusif. |
| Hold | Dokter/grooming dan stok: 15 menit. Penitipan yang disetujui: 30 menit. Waktu akhir tertera pada invoice. |
| Riwayat medis | Pelanggan melihat versi terbit dan lampiran yang terkait Booking miliknya. Catatan internal dokter terpisah. |
| Revisi medis | Versi terbit tidak ditimpa. Dokter membuat versi baru dengan alasan revisi. |
| Reminder | Mengikuti jadwal/versi terbit. Pengingat lama dibatalkan saat jadwal atau rencana kontrol berubah. |
| Grooming | Terjadwal → dikerjakan → siap dijemput → serah terima → selesai. |
| Penitipan | Pengajuan → verifikasi dokumen dan kapasitas → tagihan → lunas → check-in → check-out. |
| Kapasitas kandang | Satu hewan per unit eksklusif, termasuk waktu pembersihan. Tarif/malam disnapshot pada masa inap. |
| Perpanjangan | Satu pengajuan aktif; admin Setujui/Tolak. Menolak wajib alasan. Setuju membuat hold dan invoice tambahan. |
| Aktivasi perpanjangan | Tanggal keluar awal tetap berlaku sampai dana sah dan hold tambahan diaktifkan atomik. Callback berulang tidak menambah malam lagi. |
| Perpanjangan terlambat | Dana tetap dicatat. Hold tidak direbut dari pelanggan lain; status perlu penanganan. |
| Katalog | Filter spesies dan kategori adalah irisan. Kategori tidak sesuai direset dengan penjelasan. |
| Harga | Rupiah integer; nominal/tagihan dihitung server dan disnapshot. |
| Stok | Batch FEFO, hold sementara, saldo tidak negatif. Stok berkurang saat payment diterapkan. Kedaluwarsa tidak dijual. |
| Pengambilan | Status lunas berbeda dari selesai. Pesanan selesai setelah serah terima tercatat. |
| Pengiriman | Alamat lengkap, kontak penerima, dan koordinat tujuan terkonfirmasi wajib. |
| Kurir Toko | Kebijakan aktif, jarak rute ≤ batas, paket sesuai, window aktif, dan kuota tersedia. Window disiapkan operasional sesuai ketersediaan petugas. |
| Kurir instan | Dapat ditawarkan sekalipun dekat, mengikuti respons penyedia. |
| Kuota | HELD/CONFIRMED/FULFILLED dihitung. Window yang selesai tidak membuka jatah berulang. |
| Quote | Isi paket, alamat, versi kebijakan, dan expiry diperiksa ulang saat Checkout. |
| Dispatch | Setelah lunas dan dikemas. REQUESTING/UNKNOWN masih dianggap shipment aktif. |
| Selisih ongkir | Perlu keputusan biaya toko yang tercatat; harga pelanggan tidak berubah diam-diam. |
| Pembayaran | Hanya status backend terverifikasi. Satu payment diterapkan per invoice; dana ganda tetap direkam. |
| Dana terlambat | Invoice dapat lunas sementara alokasi menjadi perlu penanganan. Uang dan kapasitas dicatat terpisah. |
| Refund | Jumlah refund berjalan/selesai tidak melebihi dana diterima. Persetujuan tidak berarti transfer otomatis. |
| Retur | Refund tidak otomatis mengembalikan stok; stok ditambah setelah barang diterima dan diperiksa. |
| Ulasan | Hanya milik sendiri, selesai, dibayar, satu per target. Ulasan dapat diedit. Tidak menjamin seluruh penyalahgunaan hilang. |
| Moderasi | Wajib alasan; rating negatif yang sah tidak dihapus hanya karena nilainya rendah. |
| Owner | Melihat operasional/laporan tanpa mutasi. Catatan internal klinis tetap pada tenaga klinis berwenang. |
| Super Admin | Mengelola akun, peran, master dan usaha; tidak menimpa isi rekam medis terbit. |

Pengubahan pemilik hewan, penggabungan akun datang langsung ke akun online, DP, promo, retur barang per unit, dan refund gateway otomatis memerlukan prosedur tambahan bila akan digunakan. Versi ini tidak melakukan penggabungan data berdasarkan kecocokan nama/telepon.
