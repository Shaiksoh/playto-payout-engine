import { useState, useEffect } from "react";
import Dashboard from "./components/Dashboard";
import MerchantSelector from "./components/MerchantSelector";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

export { API_BASE };

export default function App() {
  const [merchants, setMerchants] = useState([]);
  const [selectedMerchant, setSelectedMerchant] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/merchants/`)
      .then((r) => r.json())
      .then((data) => {
        setMerchants(data);
        if (data.length > 0) setSelectedMerchant(data[0]);
        setLoading(false);
      })
      .catch((e) => {
        setError("Could not reach API. Is the backend running?");
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-400 text-sm">Connecting to Playto Pay...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center max-w-md">
          <div className="w-16 h-16 bg-red-900/30 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <span className="text-3xl">⚠️</span>
          </div>
          <h2 className="text-white font-semibold text-xl mb-2">Connection Error</h2>
          <p className="text-gray-400">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-emerald-500 rounded-lg flex items-center justify-center">
              <span className="text-gray-950 font-bold text-sm">P</span>
            </div>
            <span className="text-white font-semibold">Playto Pay</span>
            <span className="text-gray-600 text-sm hidden sm:block">· Payout Engine</span>
          </div>
          <MerchantSelector
            merchants={merchants}
            selected={selectedMerchant}
            onSelect={setSelectedMerchant}
          />
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-6xl mx-auto px-6 py-8">
        {selectedMerchant ? (
          <Dashboard merchant={selectedMerchant} />
        ) : (
          <div className="text-center py-24">
            <p className="text-gray-500">No merchants found. Run the seed script first.</p>
          </div>
        )}
      </main>
    </div>
  );
}
