from django.conf import settings
from accounts.permissions import ROLES, user_roles, active_role, workspace_url
from .models import StoreSettings, SiteContent
from .opening import opening_summary


def application(request):
    role = active_role(request.user)
    store = StoreSettings.objects.filter(pk=1).first()
    return {
        "store_settings": store,
        "store_hours": opening_summary(store),
        "site_content": {item.key: item for item in SiteContent.objects.filter(is_active=True)},
        "local_mode": settings.LOCAL_MODE,
        "simulation": any(
            mode == "mock"
            for mode in (settings.PAYMENT_MODE, settings.ROUTES_MODE, settings.SHIPPING_MODE)
        ),
        "google_enabled": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "map_config": {
            "tileUrl": settings.MAP_TILE_URL,
            "attribution": settings.MAP_TILE_ATTRIBUTION,
        },
        "workspace_role": role,
        "workspace_label": ROLES.get(role, ("", ""))[0],
        "workspaces": [(r, ROLES[r][0]) for r in ROLES if r in user_roles(request.user)],
        "dashboard_url": workspace_url(role) if role else "/dashboard/",
        "staff_workspace": bool(role and role != "CUSTOMER"),
        "staff_mfa_required": settings.REQUIRE_STAFF_MFA,
        "cart_count": sum(int(q) for q in request.session.get("cart", {}).values()),
    }
