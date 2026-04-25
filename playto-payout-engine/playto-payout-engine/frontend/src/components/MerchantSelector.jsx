export default function MerchantSelector({ merchants, selected, onSelect }) {
  return (
    <select
      value={selected?.id || ""}
      onChange={(e) => {
        const m = merchants.find((m) => m.id === e.target.value);
        if (m) onSelect(m);
      }}
      className="bg-gray-900 text-white border border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-emerald-500 cursor-pointer"
    >
      {merchants.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name}
        </option>
      ))}
    </select>
  );
}
