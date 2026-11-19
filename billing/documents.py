from reportlab.lib import colors
from reportlab.platypus import LongTable, TableStyle, Spacer
from core.models import StoreSettings
from core.pdf import WIDTH, GREEN, LINE, styles, text, metadata, document, money, local_date
from core.templatetags.sinau import status_label, payment_label
from .models import InvoiceLine, PaymentTransaction


def invoice_document(invoice):
    store = StoreSettings.objects.select_related("logo_file").filter(pk=1).first()
    theme = styles()
    content = [
        text("INVOICE", theme["title"]),
        text(f"{invoice.code}  |  {status_label(invoice.status)}", theme["body"]),
    ]
    if store and store.public_contact_ready:
        content.append(text(store.address, theme["muted"]))
        if store.cs_whatsapp:
            content.append(text("WhatsApp " + store.cs_whatsapp, theme["muted"]))
    target = invoice.booking or invoice.order or invoice.extension.stay.booking
    content += [
        Spacer(1, 10),
        metadata(
            [
                ("Ditagihkan kepada", invoice.customer.name),
                ("Nomor transaksi", target.code),
                ("Tanggal terbit", local_date(invoice.created_at, store)),
                (
                    "Dibayar pada" if invoice.status == "PAID" else "Batas pembayaran",
                    local_date(
                        invoice.paid_at if invoice.status == "PAID" else invoice.expires_at, store
                    ),
                ),
            ],
            theme,
        ),
        text("Rincian", theme["section"]),
    ]
    rows = [
        [text(label, theme["white"]) for label in ["Deskripsi", "Qty", "Harga satuan", "Jumlah"]]
    ]
    for line in InvoiceLine.objects.filter(invoice=invoice).order_by("created_at", "pk"):
        rows.append(
            [
                text(line.description, theme["body"]),
                text(line.quantity, theme["body"]),
                text(money(line.unit_amount_rp), theme["right"]),
                text(money(line.line_total_rp), theme["right"]),
            ]
        )
    table = LongTable(rows, colWidths=[WIDTH - 245, 35, 100, 110], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), GREEN),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
            ]
        )
    )
    total = LongTable(
        [[text("Total pembayaran", theme["body"]), text(money(invoice.total_rp), theme["amount"])]],
        colWidths=[WIDTH - 190, 190],
        hAlign="LEFT",
    )
    total.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef4ee")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    content += [table, Spacer(1, 12), total]
    payments = PaymentTransaction.objects.filter(invoice=invoice).order_by("settled_at")
    if payments.exists():
        content.append(text("Riwayat pembayaran", theme["section"]))
        for payment in payments:
            state = (
                payment_label(payment.handling_status)
                if payment.handling_status in {"REFUNDED", "PARTIALLY_REFUNDED"}
                else ("Diterima" if payment.is_applied else "Perlu ditinjau")
            )
            content.append(
                text(
                    f"{local_date(payment.settled_at, store)} | {payment_label(payment.provider)} | {money(payment.amount_rp)} | {state}",
                    theme["body"],
                )
            )
    content += [
        Spacer(1, 15),
        text(
            "Terima kasih telah mempercayakan kebutuhan dan perawatan hewan Anda kepada kami.",
            theme["body"],
        ),
    ]
    if invoice.status != "PAID":
        content.append(
            text(
                "Invoice ini bukan bukti pembayaran. Status lunas ditampilkan setelah pembayaran terkonfirmasi.",
                theme["muted"],
            )
        )
    return document(content, store, f"Invoice {invoice.code}")
