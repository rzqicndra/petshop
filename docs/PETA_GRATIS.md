# Peta tanpa billing Google: localhost hingga production

Revisi 17 November 2026. Google Maps/Routes diganti dengan Leaflet 1.9.4, OpenStreetMap raster tiles, dan openrouteservice melalui API HeiGIT. Google Login tetap tersedia dan terpisah dari peta. Tidak ada kartu Google Cloud yang diperlukan untuk stack peta ini. Tidak ada janji layanan gratis tanpa batas atau jaminan uptime provider.

## Yang sudah diimplementasikan

- Leaflet disimpan dalam static/vendor/leaflet, bukan bergantung pada CDN saat halaman dibuka. File JS/CSS diperiksa terhadap SRI resmi 1.9.4; lisensi dan checksum disertakan.
- Peta alamat tampil tanpa API key Google. Klik atau geser pin memperbarui latitude/longitude enam desimal dan membatalkan konfirmasi titik lama. Input koordinat manual tetap tersedia jika gambar peta tidak bisa dimuat.
- Tile OpenStreetMap memakai HTTPS, attribution terlihat, dan kebijakan Referrer-Policy yang tetap mengirim origin. Tidak ada prefetch/offline download atau proxy tile yang menonaktifkan cache browser. MAP_TILE_URL dan attribution dapat diganti oleh pengelola tanpa mengubah JavaScript. Public OSM tiles bersifat best effort dan tidak menyediakan SLA.
- Perhitungan jarak memakai POST /v2/directions/driving-car/json pada https://api.heigit.org. URL api.openrouteservice.org lama tidak dipakai. Key hanya di backend. Koordinat mengikuti urutan longitude,latitude yang diwajibkan ORS; hasil dalam meter dibulatkan ke atas agar 5000,1 m tidak lolos batas 5000 m.
- Moda DRIVE dipetakan ke driving-car, WALK ke foot-walking, BICYCLE ke cycling-regular. TWO_WHEELER tidak dipaksakan ke profil mobil secara diam-diam. Kebijakan pengiriman awal memakai DRIVE; hasil bukan estimasi kemacetan Google atau navigasi motor khusus.
- Cache jarak satu jam berada di PostgreSQL, dibagi antar web/worker. Cache menyimpan hash pasangan titik dan jarak, tidak nama/alamat/nomor telepon. Cache expired tidak dipakai sebagai fallback.
- Pembatas permintaan per key pada deployment ini: 30/menit dan 1500 per jendela 24 jam. Cache hit tidak menghabiskan permintaan API. Batas akun provider tetap berlaku dan dapat berubah; jika key dipakai di deployment lain, jumlah penggunaan di sana tidak dihitung oleh limiter lokal ini.
- Jika key belum ada, kuota habis, rute tidak ditemukan, atau provider gagal: Kurir Toko tidak ditawarkan berdasarkan jarak palsu. Ambil di toko dan tarif kurir instan yang benar-benar tersedia tetap bisa dipilih. Tidak ada fallback ke Google berbayar atau perhitungan garis lurus.

## Upgrade instalasi Windows yang sudah ada

1. Download ZIP terbaru, ekstrak di folder terpisah, misalnya C:\Users\Rizqi\sinau-satwa-update. Buka CMD di folder hasil ekstrak yang benar-benar memuat manage.py dan scripts.
2. Jalankan pemeriksaan, hentikan hanya aplikasi lama, lalu terapkan update:

```cmd
py scripts\install_update.py --target C:\Users\Rizqi\sinau-satwa --dry-run
docker compose -f C:\Users\Rizqi\sinau-satwa\compose.yaml stop web worker beat
py scripts\install_update.py --target C:\Users\Rizqi\sinau-satwa
```

Installer mengganti file revisi yang terdaftar, mencadangkan file lama di var/update-backups, mempertahankan secret SMTP/Midtrans/Google Login/database, menambahkan setting peta yang belum ada, dan mengubah ROUTES_MODE lama menjadi openrouteservice. Itulah satu setting provider lama yang memang dimigrasikan pada rilis ini. Nilai MAPS_BROWSER_KEY/MAPS_SERVER_KEY lama tidak dipakai oleh aplikasi. Jangan menimpa .env dengan .env.example.

3. Masuk ke folder lama dan build ulang:

```cmd
cd /d C:\Users\Rizqi\sinau-satwa
docker compose up -d --build --wait
```

Compose lokal menjalankan migrasi otomatis, termasuk delivery.0004_routeestimate. Bila menggunakan prosedur manual/production, jalankan migrate sebelum membuka fitur pengiriman. Tidak perlu seed_demo ulang atau menghapus volume. Jangan menggunakan down -v.

4. Peta pemilihan titik sudah bisa tampil. Perhitungan rute nyata masih memerlukan key akun Standard gratis pada langkah berikut.

## Mendapatkan key rute gratis

1. Buka https://account.heigit.org/ dan buat akun HeiGIT menggunakan email Anda. Selesaikan verifikasi email dan tinjau ketentuan layanan.
2. Buka Dashboard/API key. Akun mendapat key Standard gratis sesuai informasi resmi https://api.heigit.org/. Simpan key sendiri; jangan kirim di chat atau screenshot .env.
3. Edit .env instalasi lama:

```dotenv
MAP_PROVIDER=leaflet
MAP_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
MAP_TILE_ATTRIBUTION=© OpenStreetMap contributors
ROUTES_MODE=openrouteservice
ORS_API_KEY=ISI_KEY_STANDARD_ASLI_ANDA
ORS_BASE_URL=https://api.heigit.org
ORS_REQUESTS_PER_MINUTE=30
ORS_REQUESTS_PER_DAY=1500
ORS_CACHE_SECONDS=3600
```

4. Simpan, lalu terapkan:

```cmd
docker compose up -d --force-recreate --wait web worker beat
docker compose exec web python manage.py check_integrations --strict
```

check_integrations tidak lagi meminta Google Maps key. Kekurangan Biteship, kontak resmi toko, SMTP atau Google Login tetap diperiksa secara terpisah. --network menguji konektivitas TLS, bukan validitas key ORS atau keberhasilan rute.

## Uji alur sebenarnya

1. Pada data master Super Admin, isi alamat/latitude/longitude asli petshop dan nomor CS yang sah. Sahkan public_contact_ready.
2. Login pelanggan, buka Alamat pengiriman, klik peta, lengkapi alamat, penerima dan kontak, lalu konfirmasi titik yang benar. Zoom perlu digunakan untuk memilih titik secara teliti. Klik peta tidak otomatis mengisi nama jalan atau mendeteksi GPS pelanggan.
3. Buat pesanan produk baru dan pilih pengiriman. Sistem menghitung jarak dari lokasi petshop ke titik tujuan lewat backend. Kurir Toko hanya muncul bila jarak di bawah/sama dengan batas kebijakan, ukuran/berat sesuai dan window/kuota tersedia.
4. Uji alamat dekat, alamat di luar 5 km contoh, provider tanpa key, kuota habis dan jaringan gagal. Perhitungan jaringan bukan angka fixture 3200 m.
5. Biteship tetap menggunakan API key Testing untuk pengujian. Peta gratis tidak menjadikan ongkir kurir, biaya gateway pembayaran, paket API Biteship atau hosting production gratis. Masing-masing mengikuti penyedia; tidak ada transaksi berbayar yang dilakukan otomatis oleh pemasangan update.

## Production dan batas biaya

Konfigurasi Leaflet/OSM/ORS yang sama dapat dipakai di production; tidak perlu mengaktifkan Google Cloud Billing. Gunakan domain HTTPS, setelan production/Compose yang sudah ada, dan key ORS milik pengelola. Tidak ada endpoint/API key demo publik yang dipakai bersama oleh pelanggan.

Standard ORS memiliki kuota, bukan permintaan tak terbatas. Saat habis, integrasi ini gagal tertutup untuk Kurir Toko; tidak meng-upgrade paket atau menagih kartu. Akun provider dan syarat plan harus tetap ditinjau pemilik. Tile publik OSM hanya layak selama penggunaan mematuhi policy, attribution dan kapasitas wajar. Jangan menjanjikan layanan gratis dengan SLA untuk trafik berapa pun. Jika trafik bertambah, evaluasi penyedia tile yang sesuai atau host sendiri; hosting/server dapat memiliki biaya meskipun perangkat lunaknya open source.

## Referensi resmi

- https://leafletjs.com/install.html (versi stabil 1.9.4)
- https://operations.osmfoundation.org/policies/tiles/
- https://api.heigit.org/
- https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/requests-and-return-types
- https://ask.openrouteservice.org/t/free-plan-in-an-app-with-a-paid-tier-license-cc-by-sa-4-0-personal-data-and-attribution-questions/8079

Pengujian otomatis menggunakan respons ORS terkontrol, bukan key pribadi pengguna. UAT rute nyata dan cakupan jalan di sekitar toko dilakukan setelah Anda mengisi key sendiri.
