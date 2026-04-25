from django.contrib import admin
from .models import Merchant, LedgerEntry, Payout, IdempotencyKey


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "bank_account_id", "available_balance_display", "created_at"]
    search_fields = ["name", "email"]

    def available_balance_display(self, obj):
        paise = obj.available_balance_paise()
        return f"₹{paise / 100:.2f}"
    available_balance_display.short_description = "Available Balance"


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ["merchant", "entry_type", "amount_display", "description", "created_at"]
    list_filter = ["entry_type", "merchant"]
    search_fields = ["description", "reference_id"]
    readonly_fields = ["id", "created_at"]

    def amount_display(self, obj):
        return f"₹{obj.amount_paise / 100:.2f}"
    amount_display.short_description = "Amount"


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ["id_short", "merchant", "amount_display", "status", "attempt_count", "created_at"]
    list_filter = ["status", "merchant"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def id_short(self, obj):
        return str(obj.id)[:8] + "…"
    id_short.short_description = "ID"

    def amount_display(self, obj):
        return f"₹{obj.amount_paise / 100:.2f}"
    amount_display.short_description = "Amount"


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ["key_short", "merchant", "is_in_flight_display", "created_at", "expires_at"]
    readonly_fields = ["id", "created_at"]

    def key_short(self, obj):
        return obj.key[:16] + "…"
    key_short.short_description = "Key"

    def is_in_flight_display(self, obj):
        return obj.is_in_flight()
    is_in_flight_display.boolean = True
    is_in_flight_display.short_description = "In Flight?"
