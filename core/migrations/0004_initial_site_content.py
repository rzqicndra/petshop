from django.db import migrations


ROWS = [('home',
  'PETSHOP & PERAWATAN HEWAN',
  'Sahabat kecil.\nPerhatian sepenuh hati.',
  'Dari kebutuhan sehari-hari hingga waktu untuk dirawat. Kami menemani perjalanan Anda bersama mereka.',
  'images/cat-hero.jpg',
  'Kucing beristirahat dengan nyaman',
  'Booking layanan',
  'new_booking'),
 ('services',
  'LAYANAN KAMI',
  'Perawatan yang mereka butuhkan.',
  'Pilih layanan yang sesuai. Jadwal dan informasi perawatan tersimpan di akun Anda.',
  '',
  '',
  '',
  ''),
 ('care',
  'TETAP DEKAT, SETIAP HARI',
  'Anda tahu yang mereka butuhkan.',
  'Riwayat layanan, hasil pemeriksaan, dan panduan dari dokter. Tetap terhubung dengan kabar selama '
  'menginap dan pengingat jadwal perawatan.',
  'images/cat-luna.jpg',
  'Kucing beristirahat di rumah',
  'Mulai dari akun Anda',
  'register'),
 ('shop',
  'PILIHAN UNTUK SAHABAT ANDA',
  'Kebutuhan mereka.\nPilihan penuh perhatian.',
  'Makanan favorit, perawatan, dan hal kecil yang membuat hari mereka lebih nyaman.',
  'images/dog-hero.jpg',
  'Anjing menikmati waktu di rumah',
  '',
  ''),
 ('auth',
  'CARE, WITH A LITTLE MORE HEART.',
  'Satu tempat.\nSegala perhatian.',
  'Untuk kebutuhan harian dan perawatan sahabat kesayangan Anda.',
  'images/cat-hero.jpg',
  'Kucing beristirahat',
  '',
  ''),
 ('reviews',
  'CERITA PELANGGAN',
  'Pengalaman yang berarti.',
  'Setiap ulasan ditautkan ke transaksi atau layanan yang telah selesai dan dibayar.',
  '',
  '',
  '',
  ''),
 ('contact',
  'KAMI SIAP MEMBANTU',
  'Datang, sapa, dan kenali kami.',
  'Temukan toko atau hubungi tim kami untuk layanan dan pesanan Anda.',
  '',
  '',
  '',
  ''),
 ('service_page',
  'LAYANAN & PERAWATAN',
  'Dirawat dengan baik.\nDitemani dengan hati.',
  'Temukan perawatan yang dibutuhkan. Login untuk memilih hewan dan mengatur jadwal.',
  '',
  '',
  '',
  ''),
 ('products',
  'KEBUTUHAN SEHARI-HARI',
  'Pilihan untuk sahabat Anda.',
  'Lengkapi kebutuhan mereka dengan pilihan dari toko kami.',
  '',
  '',
  '',
  ''),
 ('privacy',
  'INFORMASI & KEBIJAKAN',
  'Privasi & ketentuan',
  'Privasi & ketentuan · Sinau Satwa\n'
  'INFORMASI PENGGUNA\n'
  'Privasi & ketentuan layanan.\n'
  'Informasi berikut menjelaskan penggunaan data dan alur layanan di Sinau Satwa.\n'
  'Data yang digunakan\n'
  'Nama, email, kontak, profil hewan, serta riwayat transaksi digunakan untuk menjalankan layanan. '
  'Alamat lengkap dan titik tujuan diperlukan saat memilih pengiriman. Kontak darurat digunakan sesuai '
  'persetujuan untuk layanan penitipan.\n'
  'Akses informasi\n'
  'Pelanggan dapat melihat transaksi miliknya. Staf memperoleh akses sesuai peran dan penugasan. '
  'Lampiran kesehatan serta hasil pemeriksaan disimpan secara privat. Catatan internal dokter tidak '
  'masuk ke ringkasan pelanggan.\n'
  'Peta dan pengiriman\n'
  'Peta memakai Leaflet dan sumber gambar OpenStreetMap. Penyedia gambar peta menerima permintaan '
  'browser, termasuk alamat IP dan area peta yang dilihat. Untuk menghitung jarak jalan, server '
  'mengirim koordinat asal dan tujuan ke openrouteservice/HeiGIT, tanpa nama, email atau nomor telepon '
  'dalam permintaan rute. Jarak disimpan sementara untuk mengurangi permintaan berulang. Nama, alamat '
  'dan kontak penerima dikirim ke penyedia kurir ketika Anda memilih pengiriman.\n'
  'Pembayaran dan reservasi\n'
  'Jadwal, stok, dan kuota tertentu ditahan sementara saat menunggu pembayaran. Batas waktu tertera '
  'pada tagihan. Dana yang diterima setelah reservasi berakhir tetap dicatat dan ditinjau admin untuk '
  'penyelesaian.\n'
  'Pembatalan dan bantuan transaksi\n'
  'Transaksi yang belum dibayar dapat dibatalkan sesuai tahap yang tersedia. Jika pembayaran sudah '
  'diterima atau Anda mengalami kendala pesanan, hubungi CS melalui kontak resmi. Tim kami akan '
  'memeriksa transaksi dan membantu menentukan penyelesaiannya.\n'
  'Ulasan dan permintaan data\n'
  'Ulasan ditautkan ke transaksi selesai dan dapat dimoderasi dengan alasan. Jangan menuliskan data '
  'pribadi dalam ulasan publik. Hubungi pengelola melalui kontak resmi untuk permintaan koreksi atau '
  'penanganan data.',
  '',
  '',
  '',
  '')]


def seed(apps, schema_editor):
    Content = apps.get_model("core", "SiteContent")
    for key, overline, heading, body, image, alt, label, route in ROWS:
        Content.objects.get_or_create(key=key, defaults=dict(overline=overline, heading=heading, body=body, fallback_image=image, image_alt=alt, button_label=label, link_route=route))
    Service = apps.get_model("scheduling", "Service")
    for kind, description in {"VET":"Pemeriksaan, panduan perawatan, dan pengingat kontrol dari dokter.", "GROOMING":"Perawatan yang disesuaikan dengan kebutuhan dan kondisi hewan.", "BOARDING":"Tempat beristirahat dengan pendampingan dan kabar harian untuk Anda."}.items():
        Service.objects.filter(kind=kind, description="").update(description=description)


class Migration(migrations.Migration):
    dependencies = [("core", "0003_storesettings_cs_label_storesettings_footer_text_and_more"), ("scheduling", "0003_service_description_service_image_file")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
