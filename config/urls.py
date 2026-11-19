from django.urls import path
from core import views as core
from accounts import views as accounts
from customers import views as customers
from orders import views as orders
from scheduling import views as scheduling
from billing import views as billing
from delivery import views as delivery
from care import views as care
from engagement import views as engagement
from core.admin import management_site
from accounts import staff
from core import operations

from core.master import master_center

urlpatterns = [
    path("akun/profil/", accounts.account_profile, name="account_profile"),
    path("profil/kontak/<uuid:pk>/hapus/", customers.emergency_delete, name="emergency_delete"),
    path("media/website/<uuid:pk>/", core.site_image, name="site_image"),
    path("produk/<uuid:pk>/", core.product_detail, name="product_detail"),
    path("management/", master_center),
    path("pengaturan/", master_center, name="master_center"),
    path("pengaturan/<slug:section>/", master_center, name="master_section"),
    path("pengaturan/<slug:section>/<str:pk>/", master_center, name="master_edit"),
    path("management/core/storesettings/", master_center, {"section": "toko"}),
    path("management/core/storesettings/<int:pk>/change/", master_center, {"section": "toko"}),
    path("hewan/<uuid:pk>/hapus/", customers.pet_delete, name="pet_delete"),
    path("alamat/<uuid:pk>/hapus/", customers.address_delete, name="address_delete"),
    path("", core.home, name="home"),
    path("katalog/", core.catalog_view, name="catalog"),
    path("privasi/", core.privacy, name="privacy"),
    path("produk/foto/<uuid:pk>/", core.product_image, name="product_image"),
    path("jadwal/", scheduling.timetable, name="timetable"),
    path("layanan/", core.services_view, name="services"),
    path("kontak/", core.contact_view, name="contact"),
    path("ulasan/", core.public_reviews, name="public_reviews"),
    path("health/", core.health, name="health"),
    path("login/", accounts.login_view, name="login"),
    path("register/", accounts.register_view, name="register"),
    path("forgot-password/", accounts.forgot_view, name="forgot_password"),
    path("otp/", accounts.verify_view, name="verify_otp"),
    path("otp/kirim-ulang/", accounts.resend_view, name="resend_otp"),
    path("reset-password/", accounts.reset_view, name="reset_password"),
    path("logout/", accounts.logout_view, name="logout"),
    path("workspace/", accounts.switch_workspace, name="workspace"),
    path("undangan/", staff.invite_start, name="invite_start"),
    path("operasional/akun/", staff.staff_accounts, name="staff_accounts"),
    path("operasional/pelanggan/", operations.walkin_view, name="walkin"),
    path("operasional/kasir/", operations.cashier_view, name="cashier"),
    path("operasional/kapasitas/", operations.capacity_view, name="capacity"),
    path("auth/google/", accounts.google_start, name="google_start"),
    path("auth/google/callback/", accounts.google_callback, name="google_callback"),
    path("auth/google/tautkan/", accounts.google_link, name="google_link"),
    path("keamanan/", accounts.security_view, name="security"),
    path("keamanan/konfirmasi/", accounts.mfa_login, name="mfa_login"),
    path("dashboard/", core.dashboard, name="dashboard"),
    path("staf/<slug:role_slug>/", core.dashboard, name="staff_dashboard"),
    path("hewan/", customers.pets_view, name="pets"),
    path("hewan/<uuid:pk>/", customers.pets_view, name="pet_edit"),
    path("alamat/", customers.addresses_view, name="addresses"),
    path("alamat/<uuid:pk>/", customers.addresses_view, name="address_edit"),
    path("profil/", customers.profile_view, name="profile"),
    path("keranjang/", orders.cart_view, name="cart"),
    path("keranjang/ubah/", orders.cart_update, name="cart_update"),
    path("checkout/", orders.checkout_view, name="checkout"),
    path("pesanan/", orders.orders_list, name="orders"),
    path("pesanan/<uuid:pk>/", orders.order_detail, name="order_detail"),
    path("booking/baru/", scheduling.new_booking, name="new_booking"),
    path("booking/", scheduling.bookings_list, name="bookings"),
    path("booking/<uuid:pk>/", scheduling.booking_detail, name="booking_detail"),
    path("tagihan/<uuid:pk>/status/", billing.invoice_status, name="invoice_status"),
    path("tagihan/<uuid:pk>/", billing.invoice_view, name="invoice"),
    path("tagihan/<uuid:pk>/pdf/", billing.invoice_pdf, name="invoice_pdf"),
    path("pembayaran/kembali/", billing.payment_return, name="payment_return"),
    path("cek-pesanan", billing.payment_return, name="payment_return_legacy"),
    path("cek-pesanan/", billing.payment_return),
    path("webhooks/midtrans/", billing.midtrans_webhook, name="midtrans_webhook"),
    path("webhooks/biteship/", delivery.biteship_webhook, name="biteship_webhook"),
    path("pengiriman/", delivery.shipments_view, name="shipments"),
    path("pengiriman/<uuid:pk>/", delivery.shipments_view, name="shipment_detail"),
    path("rekam-medis/<uuid:pk>/pdf/", care.medical_pdf, name="medical_pdf"),
    path("berkas/<uuid:pk>/", core.file_download, name="file_download"),
    path("ulasan/tulis/<str:kind>/<uuid:pk>/", engagement.review_view, name="review"),
    path("operasional/ulasan/", engagement.moderation_view, name="moderation"),
    path("operasional/stok/", core.inventory_view, name="inventory"),
    path("operasional/laporan/", core.reports_view, name="reports"),
    path("operasional/audit/", core.audit_view, name="audit"),
    path("management/", management_site.urls),
]
