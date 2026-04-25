function formatINR(paise) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(paise / 100);
}

function formatDate(iso) {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function LedgerTable({ entries }) {
  if (!entries || entries.length === 0) {
    return (
      <div className="text-center py-12 text-gray-600">
        <p>No ledger entries yet.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800">
            {["Type", "Amount", "Description", "Date"].map((h) => (
              <th key={h} className="text-left text-gray-500 font-medium pb-3 pr-6">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {entries.map((e) => (
            <tr key={e.id} className="hover:bg-gray-900/50 transition-colors">
              <td className="py-3.5 pr-6">
                <span
                  className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium uppercase tracking-wide ${
                    e.type === "credit"
                      ? "bg-emerald-500/15 text-emerald-400"
                      : "bg-red-500/15 text-red-400"
                  }`}
                >
                  {e.type === "credit" ? "↓ CR" : "↑ DR"}
                </span>
              </td>
              <td
                className={`py-3.5 pr-6 font-medium tabular-nums ${
                  e.type === "credit" ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {e.type === "credit" ? "+" : "−"}
                {formatINR(e.amount_paise)}
              </td>
              <td className="py-3.5 pr-6 text-gray-400 max-w-xs truncate">
                {e.description}
              </td>
              <td className="py-3.5 text-gray-500 whitespace-nowrap">
                {formatDate(e.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
