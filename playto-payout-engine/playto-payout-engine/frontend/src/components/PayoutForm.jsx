import { useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { API_BASE } from "../App";

function formatINR(paise) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(paise / 100);
}

export default function PayoutForm({ merchant, availablePaise, onSuccess }) {
  const [amountRupees, setAmountRupees] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null); // { type: 'success'|'error', message, data }

  const amountPaise = Math.round(parseFloat(amountRupees || "0") * 100);
  const isValid = amountPaise >= 100 && amountPaise <= availablePaise;

  const handleSubmit = async () => {
    if (!isValid || submitting) return;

    setSubmitting(true);
    setResult(null);

    // Auto-generate a fresh idempotency key per submission
    const idempotencyKey = uuidv4();

    try {
      const res = await fetch(
        `${API_BASE}/payouts/?merchant_id=${merchant.id}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify({
            amount_paise: amountPaise,
            bank_account_id: merchant.bank_account_id,
          }),
        }
      );

      const data = await res.json();

      if (res.ok) {
        setResult({
          type: "success",
          message: `Payout of ${formatINR(amountPaise)} queued successfully`,
          data,
        });
        setAmountRupees("");
        onSuccess();
      } else {
        setResult({
          type: "error",
          message: data.error || "Payout failed",
          data,
        });
      }
    } catch (e) {
      setResult({ type: "error", message: "Network error. Please try again." });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
      <h2 className="text-white font-semibold mb-1">Request Payout</h2>
      <p className="text-gray-500 text-sm mb-5">
        Withdraw to{" "}
        <span className="text-gray-400 font-mono text-xs">
          {merchant.bank_account_id}
        </span>
      </p>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1">
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">
              ₹
            </span>
            <input
              type="number"
              value={amountRupees}
              onChange={(e) => setAmountRupees(e.target.value)}
              placeholder="0.00"
              min="1"
              step="0.01"
              className="w-full bg-gray-800 border border-gray-700 text-white rounded-xl px-4 py-3 pl-8 focus:outline-none focus:border-emerald-500 placeholder-gray-600"
            />
          </div>
          {amountRupees && (
            <p
              className={`text-xs mt-1.5 ${
                amountPaise > availablePaise
                  ? "text-red-400"
                  : "text-gray-500"
              }`}
            >
              {amountPaise > availablePaise
                ? `Exceeds available balance (${formatINR(availablePaise)})`
                : `Available: ${formatINR(availablePaise)}`}
            </p>
          )}
        </div>

        <button
          onClick={handleSubmit}
          disabled={!isValid || submitting}
          className="px-6 py-3 bg-emerald-500 text-gray-950 font-semibold rounded-xl hover:bg-emerald-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2 whitespace-nowrap"
        >
          {submitting ? (
            <>
              <div className="w-4 h-4 border-2 border-gray-950 border-t-transparent rounded-full animate-spin" />
              Processing...
            </>
          ) : (
            "Request Payout"
          )}
        </button>
      </div>

      {result && (
        <div
          className={`mt-4 p-3 rounded-xl text-sm ${
            result.type === "success"
              ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400"
              : "bg-red-500/10 border border-red-500/20 text-red-400"
          }`}
        >
          {result.message}
        </div>
      )}
    </div>
  );
}
