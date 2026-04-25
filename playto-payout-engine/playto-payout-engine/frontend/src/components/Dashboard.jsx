import { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../App";
import BalanceCards from "./BalanceCards";
import PayoutForm from "./PayoutForm";
import PayoutHistory from "./PayoutHistory";
import LedgerTable from "./LedgerTable";

export default function Dashboard({ merchant }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("payouts");

  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/merchants/${merchant.id}/`);
      const data = await res.json();
      setSummary(data);
    } catch (e) {
      console.error("Failed to fetch summary", e);
    } finally {
      setLoading(false);
    }
  }, [merchant.id]);

  // Initial fetch
  useEffect(() => {
    setLoading(true);
    setSummary(null);
    fetchSummary();
  }, [fetchSummary]);

  // Live polling every 3 seconds for payout status updates
  useEffect(() => {
    const interval = setInterval(fetchSummary, 3000);
    return () => clearInterval(interval);
  }, [fetchSummary]);

  if (loading || !summary) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-semibold text-white">
          {summary.merchant.name}
        </h1>
        <p className="text-gray-500 text-sm mt-0.5">{summary.merchant.email}</p>
      </div>

      {/* Balance cards */}
      <BalanceCards balance={summary.balance} />

      {/* Payout form */}
      <PayoutForm
        merchant={summary.merchant}
        availablePaise={summary.balance.available_paise}
        onSuccess={fetchSummary}
      />

      {/* Tabs */}
      <div>
        <div className="flex gap-1 border-b border-gray-800 mb-4">
          {[
            { id: "payouts", label: "Payout History" },
            { id: "ledger", label: "Ledger" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === tab.id
                  ? "text-emerald-400 border-b-2 border-emerald-400"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "payouts" && (
          <PayoutHistory payouts={summary.payouts} onRefresh={fetchSummary} />
        )}
        {activeTab === "ledger" && <LedgerTable entries={summary.ledger} />}
      </div>
    </div>
  );
}
