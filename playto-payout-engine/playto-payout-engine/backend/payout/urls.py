from django.urls import path
from .views import (
    MerchantListView,
    MerchantDetailView,
    PayoutCreateView,
    PayoutDetailView,
    PayoutListView,
    HealthView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("merchants/", MerchantListView.as_view(), name="merchant-list"),
    path("merchants/<uuid:merchant_id>/", MerchantDetailView.as_view(), name="merchant-detail"),
    path("payouts/", PayoutCreateView.as_view(), name="payout-create"),
    path("payouts/list/", PayoutListView.as_view(), name="payout-list"),
    path("payouts/<uuid:payout_id>/", PayoutDetailView.as_view(), name="payout-detail"),
]
