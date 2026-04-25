"""
API Views — kept intentionally thin.

Views validate input, delegate to services, and format output.
They do not contain business logic.
"""

import uuid
import logging

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Merchant, Payout
from .serializers import PayoutRequestSerializer, PayoutSerializer, MerchantSerializer
from .services import create_payout, get_merchant_summary

logger = logging.getLogger("payout")


class MerchantListView(APIView):
    """GET /api/v1/merchants/ — list all merchants (for the dashboard selector)."""

    def get(self, request):
        merchants = Merchant.objects.all()
        serializer = MerchantSerializer(merchants, many=True)
        return Response(serializer.data)


class MerchantDetailView(APIView):
    """GET /api/v1/merchants/<id>/ — full dashboard summary."""

    def get(self, request, merchant_id):
        merchant = get_object_or_404(Merchant, pk=merchant_id)
        summary = get_merchant_summary(merchant)
        return Response(summary)


class PayoutCreateView(APIView):
    """
    POST /api/v1/payouts/

    Required header: Idempotency-Key (UUID string)
    Body: { "amount_paise": int, "bank_account_id": str }

    The merchant is identified by query param ?merchant_id=<uuid>.
    In production this would come from an auth token.
    """

    def post(self, request):
        # In prod: merchant from JWT. Here: query param for simplicity.
        merchant_id = request.query_params.get("merchant_id") or request.data.get("merchant_id")
        if not merchant_id:
            return Response({"error": "merchant_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        merchant = get_object_or_404(Merchant, pk=merchant_id)

        # Validate idempotency key
        idempotency_key_str = request.headers.get("Idempotency-Key", "")
        if not idempotency_key_str:
            return Response(
                {"error": "Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            uuid.UUID(idempotency_key_str)
        except ValueError:
            return Response(
                {"error": "Idempotency-Key must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request body
        serializer = PayoutRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        response_body, http_status = create_payout(
            merchant=merchant,
            amount_paise=serializer.validated_data["amount_paise"],
            bank_account_id=serializer.validated_data["bank_account_id"],
            idempotency_key_str=idempotency_key_str,
        )

        # If a new payout was created, kick off the background worker
        if http_status == 201 and "id" in response_body:
            from .tasks import process_payout_task
            process_payout_task.delay(response_body["id"])
            logger.info(f"Enqueued processing task for payout {response_body['id']}")

        return Response(response_body, status=http_status)


class PayoutDetailView(APIView):
    """GET /api/v1/payouts/<id>/ — single payout status."""

    def get(self, request, payout_id):
        payout = get_object_or_404(Payout, pk=payout_id)
        serializer = PayoutSerializer(payout)
        return Response(serializer.data)


class PayoutListView(APIView):
    """GET /api/v1/payouts/?merchant_id=<uuid> — all payouts for a merchant."""

    def get(self, request):
        merchant_id = request.query_params.get("merchant_id")
        if not merchant_id:
            return Response({"error": "merchant_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        merchant = get_object_or_404(Merchant, pk=merchant_id)
        payouts = Payout.objects.filter(merchant=merchant).order_by("-created_at")
        serializer = PayoutSerializer(payouts, many=True)
        return Response(serializer.data)


class HealthView(APIView):
    """GET /api/v1/health/ — liveness probe."""

    def get(self, request):
        from django.db import connection
        try:
            connection.ensure_connection()
            db_ok = True
        except Exception:
            db_ok = False

        return Response({
            "status": "ok" if db_ok else "degraded",
            "database": "connected" if db_ok else "disconnected",
        }, status=200 if db_ok else 503)
