import { weatherKind } from "./dashboardOverview";

/** Local vector artwork: no remote image request or provider URL in the browser. */
export function WeatherSymbol({ symbol }: { symbol?: string | null }) {
  const kind = weatherKind(symbol);
  return <svg viewBox="0 0 100 100" className={`weather-symbol weather-symbol-${kind}`} aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
    {(kind === "sun" || kind === "partlycloudy") && <g stroke="#b77700" fill="#ffd45b"><circle cx={kind === "sun" ? 50 : 34} cy={kind === "sun" ? 50 : 34} r="17"/><path d={kind === "sun" ? "M50 8v10M50 82v10M8 50h10M82 50h10M20 20l7 7M73 73l7 7M20 80l7-7M73 27l7-7" : "M34 5v6M5 34h6M13 13l5 5M55 13l-5 5"}/></g>}
    {kind === "night" && <path d="M65 12a36 36 0 1 0 23 53A33 33 0 0 1 65 12Z" fill="#b8d6e8"/>}
    {!["sun", "night", "unknown"].includes(kind) && <path d="M23 61C5 61 6 37 24 37C27 11 65 12 69 38C93 33 99 61 77 61Z" fill="#c9e0e5"/>}
    {(kind === "rain" || kind === "sleet") && <path d="m27 73-6 12m30-12-6 12m30-12-6 12" stroke="#2272a0"/>}
    {(kind === "snow" || kind === "sleet") && <path d="M50 73v18m-8-14 16 10m-16 0 16-10" stroke="#2272a0"/>}
    {kind === "fog" && <path d="M17 73h66M25 85h50"/>}
    {kind === "thunder" && <path d="m52 65-13 15h14l-7 15 23-22H54l7-8" stroke="#b77700" fill="#ffd45b"/>}
    {kind === "unknown" && <><circle cx="50" cy="50" r="35"/><path d="M38 38c0-18 29-18 25 1-2 9-13 8-13 20M50 72h.1"/></>}
  </svg>;
}

export function MetroSymbol() {
  return <svg viewBox="0 0 100 100" className="metro-symbol" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"><rect x="23" y="10" width="54" height="67" rx="12" fill="#d7f4eb"/><path d="M32 25h36v25H32z" fill="#fff"/><path d="M39 18h22M35 77l-12 14m42-14 12 14M28 87h44"/><circle cx="36" cy="63" r="4" fill="currentColor"/><circle cx="64" cy="63" r="4" fill="currentColor"/></svg>;
}
