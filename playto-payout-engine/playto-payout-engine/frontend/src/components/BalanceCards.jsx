function formatINR(paise) {
  const rupees = paise / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(rupees);
}

export default function BalanceCards({ balance }) {
  const cards = [
    {
      label: "Available Balance",
      value: formatINR(balance.available_paise),
      sublabel: "Ready to withdraw",
      color: "emerald",
      icon: "💰",
    },
    {
      label: "Held Balance",
      value: formatINR(balance.held_paise),
      sublabel: "Pending & processing",
      color: "amber",
      icon: "⏳",
    },
    {
      label: "Total Earned",
      value: formatINR(balance.total_credits_paise),
      sublabel: "Lifetime credits",
      color: "blue",
      icon: "📈",
    },
  ];

  const colorMap = {
    emerald: {
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/20",
      text: "text-emerald-400",
      icon: "bg-emerald-500/20",
    },
    amber: {
      bg: "bg-amber-500/10",
      border: "border-amber-500/20",
      text: "text-amber-400",
      icon: "bg-amber-500/20",
    },
    blue: {
      bg: "bg-blue-500/10",
      border: "border-blue-500/20",
      text: "text-blue-400",
      icon: "bg-blue-500/20",
    },
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {cards.map((card) => {
        const c = colorMap[card.color];
        return (
          <div
            key={card.label}
            className={`rounded-2xl border ${c.border} ${c.bg} p-5`}
          >
            <div className="flex items-start justify-between mb-3">
              <p className="text-gray-400 text-xs font-medium uppercase tracking-wider">
                {card.label}
              </p>
              <span className={`text-base rounded-lg p-1.5 ${c.icon}`}>
                {card.icon}
              </span>
            </div>
            <p className={`text-2xl font-bold ${c.text}`}>{card.value}</p>
            <p className="text-gray-600 text-xs mt-1">{card.sublabel}</p>
          </div>
        );
      })}
    </div>
  );
}
