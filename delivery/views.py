import json
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from accounts.models import User
from accounts.permissions import verified_login, active_role, READ_ALL, OPS, require_role
from core.services import BusinessError, commerce_transaction, fingerprint
from core.files import store_upload
from .models import Shipment, DeliveryAssignment
from . import services, providers


@verified_login
def shipments_view(request, pk=None):
    role = active_role(request.user)
    if role in READ_ALL:
        qs = Shipment.objects.select_related("order__customer", "quote")
    elif request.user.can_deliver:
        qs = Shipment.objects.filter(
            pk__in=DeliveryAssignment.objects.filter(courier_user=request.user).values(
                "shipment_id"
            )
        ).select_related("order__customer", "quote")
    else:
        qs = Shipment.objects.none()
    shipment = get_object_or_404(qs, pk=pk) if pk else None
    if request.method == "POST" and shipment:
        try:
            action = request.POST.get("action")
            if action == "assign":
                courier = get_object_or_404(
                    User, pk=request.POST.get("courier"), is_active=True, can_deliver=True
                )
                services.assign_internal(request.user, shipment, courier)
            elif action == "reconcile":
                services.reconcile_shipment(request.user, shipment)
            elif action == "approve_cost":
                services.approve_dispatch_cost(
                    request.user, shipment, request.POST.get("reason", "")[:2000]
                )
            elif action == "delivered":
                assignment = get_object_or_404(
                    DeliveryAssignment, shipment=shipment, courier_user=request.user
                )
                proof = store_upload(request.user, request.FILES.get("file"), "DELIVERY_PROOF")
                services.complete_internal(
                    request.user, assignment, request.POST.get("recipient_name", "")[:150], proof
                )
            elif action == "start_internal":
                assignment = get_object_or_404(
                    DeliveryAssignment, shipment=shipment, courier_user=request.user
                )
                services.start_internal(request.user, assignment)
            elif action == "mock_delivered":
                require_role(request.user, OPS)
                if not settings.LOCAL_MODE or shipment.provider != "MOCK":
                    raise BusinessError("Simulasi tidak tersedia untuk pengiriman ini.")
                with commerce_transaction():
                    locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
                    services.apply_shipment_status(
                        locked,
                        {"reference_id": locked.request_key, "status": "delivered"},
                        "mock-delivered",
                    )
            else:
                raise BusinessError("Tindakan tidak tersedia.")
            messages.success(request, "Pengiriman diperbarui.")
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
        except Exception:
            messages.error(
                request,
                "Pemeriksaan kurir belum selesai. Pengiriman tetap tercatat untuk rekonsiliasi.",
            )
        return redirect("shipment_detail", pk=pk)
    from orders.models import OrderAddressSnapshot

    return render(
        request,
        "delivery/shipments.html",
        {
            "shipments": qs.order_by("-created_at")[:100],
            "shipment": shipment,
            "address": (
                OrderAddressSnapshot.objects.filter(order=shipment.order).first()
                if shipment
                else None
            ),
            "assignment": (
                DeliveryAssignment.objects.filter(shipment=shipment).first() if shipment else None
            ),
            "couriers": User.objects.filter(is_active=True, can_deliver=True),
            "can_operate": role in OPS,
        },
    )


@csrf_exempt
@require_POST
def biteship_webhook(request):
    if not providers.authenticated_webhook(request):
        return JsonResponse({"error": "unauthorized"}, status=403)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError
        provider_id = payload.get("order_id") or payload.get("id")
        shipment = Shipment.objects.filter(
            provider="BITESHIP", provider_shipment_id=provider_id
        ).first()
        if not shipment:
            return JsonResponse({"ok": True, "matched": False})
        data = providers.get_external_shipment(provider_id)
        with commerce_transaction():
            locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
            services.apply_shipment_status(
                locked, data, fingerprint({"id": provider_id, "status": data.get("status")})
            )
        return JsonResponse({"ok": True})
    except (ValueError, BusinessError):
        return JsonResponse({"error": "invalid notification"}, status=400)
    except Exception:
        return JsonResponse({"error": "temporary verification failure"}, status=503)
