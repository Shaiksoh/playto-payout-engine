"""
Seed script: python manage.py seed_merchants

Creates 3 merchants with realistic transaction history.
Run this after migrations.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from payout.models import Merchant, LedgerEntry, Payout


class Command(BaseCommand):
    help = "Seed the database with test merchants and transaction history"

    def handle(self, *args, **options):
        self.stdout.write("Seeding merchants...")

        with transaction.atomic():
            # Clear existing data
            LedgerEntry.objects.all().delete()
            Payout.objects.all().delete()
            Merchant.objects.all().delete()

            self._seed_arjun()
            self._seed_priya()
            self._seed_kiran()

        self.stdout.write(self.style.SUCCESS("✓ Seeded 3 merchants successfully"))

    def _seed_arjun(self):
        """Arjun — a Bangalore-based freelance developer. Healthy balance."""
        m = Merchant.objects.create(
            name="Arjun Sharma",
            email="arjun@devcraft.in",
            bank_account_id="HDFC0001234567",
        )

        entries = [
            (LedgerEntry.CREDIT, 250_000, "Payment from Acme Corp (USA) — logo redesign"),
            (LedgerEntry.CREDIT, 180_000, "Payment from TechStart Inc — API integration sprint"),
            (LedgerEntry.CREDIT, 320_000, "Payment from CloudBase LLC — 3-month retainer"),
            (LedgerEntry.DEBIT,  100_000, "Payout initiated to bank account HDFC0001234567"),
            (LedgerEntry.CREDIT,  50_000, "Refund for failed payout (bank rejected)"),
            (LedgerEntry.CREDIT, 150_000, "Payment from DataFlow Analytics — dashboard build"),
            (LedgerEntry.DEBIT,  200_000, "Payout initiated to bank account HDFC0001234567"),
        ]

        for entry_type, amount, desc in entries:
            LedgerEntry.objects.create(
                merchant=m,
                entry_type=entry_type,
                amount_paise=amount,
                description=desc,
            )

        self.stdout.write(f"  Created: {m.name} (balance: ₹{m.available_balance_paise()/100:.2f})")

    def _seed_priya(self):
        """Priya — a Mumbai-based content creator. Moderate balance, few payouts."""
        m = Merchant.objects.create(
            name="Priya Nair",
            email="priya@contentwave.io",
            bank_account_id="ICICI9876543210",
        )

        entries = [
            (LedgerEntry.CREDIT, 75_000,  "YouTube sponsorship — GreenLeaf Supplements"),
            (LedgerEntry.CREDIT, 120_000, "Course sales — 'Mastering Reels for Brands'"),
            (LedgerEntry.CREDIT, 45_000,  "Instagram collab — MindfulBrew Tea"),
            (LedgerEntry.DEBIT,  80_000,  "Payout initiated to bank account ICICI9876543210"),
            (LedgerEntry.CREDIT, 60_000,  "Newsletter sponsorship — Fintech Weekly"),
            (LedgerEntry.CREDIT, 90_000,  "Brand deal — FitFuel Protein"),
        ]

        for entry_type, amount, desc in entries:
            LedgerEntry.objects.create(
                merchant=m,
                entry_type=entry_type,
                amount_paise=amount,
                description=desc,
            )

        self.stdout.write(f"  Created: {m.name} (balance: ₹{m.available_balance_paise()/100:.2f})")

    def _seed_kiran(self):
        """Kiran — a Hyderabad agency owner. Large volume, multiple payouts."""
        m = Merchant.objects.create(
            name="Kiran Reddy",
            email="kiran@pixelforge.agency",
            bank_account_id="SBI0000987654",
        )

        entries = [
            (LedgerEntry.CREDIT, 500_000,  "Client: GlobalRetail — Brand identity project"),
            (LedgerEntry.CREDIT, 380_000,  "Client: NovaMed — Medical website + app UI"),
            (LedgerEntry.DEBIT,  200_000,  "Payout initiated to bank account SBI0000987654"),
            (LedgerEntry.CREDIT, 220_000,  "Client: ZephyrLogistics — Dashboard design"),
            (LedgerEntry.DEBIT,  150_000,  "Payout initiated to bank account SBI0000987654"),
            (LedgerEntry.CREDIT, 410_000,  "Client: NovaMed — Phase 2 development"),
            (LedgerEntry.DEBIT,  300_000,  "Payout initiated to bank account SBI0000987654"),
            (LedgerEntry.CREDIT, 160_000,  "Client: UrbanEats — Mobile app design"),
        ]

        for entry_type, amount, desc in entries:
            LedgerEntry.objects.create(
                merchant=m,
                entry_type=entry_type,
                amount_paise=amount,
                description=desc,
            )

        self.stdout.write(f"  Created: {m.name} (balance: ₹{m.available_balance_paise()/100:.2f})")
