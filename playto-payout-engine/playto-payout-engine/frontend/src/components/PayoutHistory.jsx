function StatusBadge({ status }) {
  const map = {
    pending: { text: "Pending", cls: "bg-gray-700 text-gray-300" },
    processing: { text: "Processing", cls: "bg-amber-500/20 text-amber-400 animate-pulse" },
    completed: { text: "Completed", cls: "bg-emerald-500/20 text-emerald-400" },
    failed: { text: "Failed", cls: "bg-red-500/20 text-red-400" },
  };
  const { text, cls } = map[status] || { text: status, cls: "bg-gray-700 text-gray-400" };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {status === "processing" && (
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 mr-1.5 animate-ping" />
      )}
      {text}
    </span>
  );
}

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

export default function PayoutHistory({ payouts }) {
  if (!payouts || payouts.length === 0) {
    return (
      <div className="text-center py-12 text-gray-600">
        <p>No payouts yet. Request one above.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800">
            {["Amount", "Bank Account", "Status", "Attempts", "Date"].map((h) => (
              <th key={h} className="text-left text-gray-500 font-medium pb-3 pr-6">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {payouts.map((p) => (
            <tr key={p.id} className="hover:bg-gray-900/50 transition-colors">
              <td className="py-3.5 pr-6 text-white font-medium">
                {formatINR(p.amount_paise)}
              </td>
              <td className="py-3.5 pr-6 text-gray-400 font-mono text-xs">
                {p.bank_account_id}
              </td>
              <td className="py-3.5 pr-6">
                <StatusBadge status={p.status} />
                {p.failure_reason && (
                  <p className="text-red-400/70 text-xs mt-1">{p.failure_reason}</p>
                )}
              </td>
              <td className="py-3.5 pr-6 text-gray-500">
                {p.attempt_count}
              </td>
              <td className="py-3.5 text-gray-500">
                {formatDate(p.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
