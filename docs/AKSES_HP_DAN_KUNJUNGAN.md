# Akses HP dan kunjungan dokter

## Akses dari HP lewat Wi-Fi yang sama

Jalankan di Windows CMD dari folder proyek:

```cmd
py scripts\enable_lan.py
docker compose up -d --build --force-recreate --wait web worker beat
```

Script menampilkan URL yang harus dibuka di HP. Gunakan alamat IPv4 laptop tersebut,
bukan `localhost`: localhost di HP merujuk ke HP sendiri. Jika laptop memiliki beberapa
adapter, jalankan `ipconfig`, pilih IPv4 adapter Wi-Fi/Ethernet yang dipakai HP, lalu:

```cmd
py scripts\enable_lan.py --host 192.168.1.10
```

Ganti alamat contoh dengan IPv4 laptop. Script hanya menerima alamat jaringan pribadi.
Port web dibuka pada interface laptop agar localhost dan IPv4 Wi-Fi bisa dipakai.
Host dan origin CSRF ditambahkan, dan debug
dimatikan. Nilai SMTP, kunci, database, callback layanan, dan APP_URL tetap tersimpan.
Mailpit, PostgreSQL, dan Redis tidak ikut dibuka ke Wi-Fi.

Jika browser HP masih gagal terhubung, buka PowerShell sebagai Administrator lalu
jalankan perintah firewall yang dicetak script. Atur jaringan Wi-Fi Windows yang
dipercaya sebagai **Private**. Aturan firewall dibatasi pada port web dan LocalSubnet.
Pastikan HP tidak memakai guest Wi-Fi, AP/client isolation, atau VPN yang memisahkan
koneksi antarperangkat. Jalankan kembali script jika IPv4 laptop berubah.

Pengujian login email/password dan pemilihan pin alamat secara manual dapat dilakukan
lewat LAN. Login Google memerlukan callback yang didaftarkan ke Google; gunakan
localhost pada laptop atau alamat HTTPS terdaftar untuk alur itu. Fitur lokasi otomatis
di browser HP juga dapat memerlukan HTTPS. Konfigurasi LAN tidak membuat domain HTTPS
atau mengubah pendaftaran callback penyedia layanan.

## Kehadiran konsultasi

Dokter yang ditugaskan mengonfirmasi **Pelanggan hadir** setelah pelanggan dan hewan
tiba. Konfirmasi dibuka mulai 30 menit sebelum jadwal. Setelah itu dokter dapat
menekan **Mulai layanan** dan mengisi hasil pemeriksaan seperti biasa.

**Tidak hadir** baru dapat dicatat setelah waktu mulai ditambah toleransi (awal 15 menit).
Catatan ketidakhadiran wajib diisi. Booking ditutup dengan status **Tidak hadir**,
slot dilepas, pengingat dibatalkan, dan pemeriksaan tidak dapat dimulai.
Pembayaran lunas tetap tercatat; tidak ada pengembalian dana otomatis.

Admin dapat mengubah toleransi di **Data master > Profil toko**. Kunjungan lama
yang sudah diperiksa ditandai hadir saat migrasi, sehingga riwayat tetap dapat dibaca.

## Dokumen dan ulasan

PDF invoice mengikuti hak akses detail pembayaran, termasuk penolakan invoice yang
ditutup bagi pelanggan. Dokter mengakses ringkasan pemeriksaan pasiennya; catatan
internal dan draft tetap tidak masuk ke PDF pelanggan.

Rating berasal dari ulasan berstatus dipublikasikan. Menyembunyikan ulasan memperbarui
rata-rata, jumlah, dan distribusi. Penulisan ulasan tetap mensyaratkan transaksi selesai,
lunas, dan milik pelanggan yang login.
