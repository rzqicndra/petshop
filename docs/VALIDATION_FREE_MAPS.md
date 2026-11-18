# Verifikasi peta gratis — 17 November 2026

- Full suite PostgreSQL 17.10: 106 tes lulus, termasuk 10 tes peta/rute baru.
- Sesudah menambah satu kasus migrasi konfigurasi Google, tiga tes installer lulus (dua sudah termasuk suite awal di atas). Total kode saat ini mempunyai 107 kasus.
- Migrasi kosong dan makemigrations --check: lulus; migrasi delivery.0004_routeestimate disertakan.
- collectstatic dan node --check static/js/maps.js: lulus.
- check --deploy --fail-level WARNING: lulus pada konfigurasi production dengan mode ORS, tanpa memanggil provider.
- Browser widget aktual memakai Leaflet lokal dan tile OSM nyata: peta tampil, attribution terlihat; klik peta mengisi koordinat enam desimal dan menghapus konfirmasi titik lama. Pengujian browser menggunakan fixture widget publik, bukan login pelanggan atau UAT private dashboard. Halaman alamat Django diuji melalui test client.
- Kontrak HTTP ORS diuji dengan mock: urutan longitude/latitude, header key backend, endpoint HeiGIT baru, meter, pembulatan ke atas di batas 5 km, cache/expiry, invalid input/respons, 429 tanpa jarak palsu, quota guard sebelum request.
- Tidak ada key ORS pengguna untuk uji end-to-end jaringan. Rute nyata di wilayah toko perlu diuji sesudah key dimasukkan.
- Leaflet JS/CSS 1.9.4 sesuai SRI resmi; lisensi dan checksum assets disertakan. Tidak ada tile peta yang dibundel dalam ZIP.
- Tidak ada perubahan dependency Python. Docker daemon/production container tidak tersedia untuk dieksekusi pada lingkungan ini; konfigurasi production bukan bukti telah deploy.
- Tidak ada klaim gratis tanpa batas/SLA: OSM best effort dan kuota ORS berlaku. API Biteship, pengiriman, pembayaran dan hosting mempunyai ketentuan/biaya masing-masing.
