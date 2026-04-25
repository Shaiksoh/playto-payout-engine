from rest_framework import serializers
from .models import Payout, LedgerEntry, Merchant


class PayoutRequestSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=100)  # Minimum ₹1
    bank_account_id = serializers.CharField(max_length=100)


class PayoutSerializer(serializers.ModelSerializer):
    amount_inr = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = [
            "id", "merchant_id", "amount_paise", "amount_inr",
            "bank_account_id", "status", "attempt_count",
            "failure_reason", "created_at", "updated_at",
        ]

    def get_amount_inr(self, obj):
        return f"{obj.amount_paise / 100:.2f}"


class LedgerEntrySerializer(serializers.ModelSerializer):
    amount_inr = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = [
            "id", "entry_type", "amount_paise", "amount_inr",
            "description", "reference_id", "created_at",
        ]

    def get_amount_inr(self, obj):
        return f"{obj.amount_paise / 100:.2f}"


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ["id", "name", "email", "bank_account_id", "created_at"]
