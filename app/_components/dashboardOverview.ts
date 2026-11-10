/** Presentation-only rules. Never write or infer new Core facts. */
export type OverviewEvent = {
  id: string | number; title: string; event_date: string; event_time?: string | null;
  location?: string | null; member_id?: number | null; member?: string | null;
};
export type OverviewActivity = {
  id: number; name: string; schedule?: string | null; paused_until?: string | null;
  location?: string | null; member_id?: number | null; member?: string | null;
};
export const overviewSettings = { showActivitiesCard: false, datedDays: 5, maxItems: 4 };

const days = ["søndag", "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag"];
const normalized = (value: string) => value.normalize("NFKC").toLocaleLowerCase("nb-NO").replace(/[^\p{L}\p{N}]+/gu, " ").trim();

function calendarDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? date : null;
}

export function occurrenceParts(item: OverviewEvent, timeZone: string) {
  if (item.event_date.length === 10) return { date: item.event_date, time: item.event_time?.slice(0, 5) || "" };
  // Offset timestamps are instants; offset-free values are already household wall time.
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(item.event_date)) {
    return { date: item.event_date.slice(0, 10), time: item.event_time?.slice(0, 5) || item.event_date.slice(11, 16) };
  }
  const instant = new Date(item.event_date);
  if (!Number.isFinite(instant.getTime())) return { date: "", time: "" };
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(instant);
  const part = (key: string) => parts.find(value => value.type === key)?.value || "";
  return { date: `${part("year")}-${part("month")}-${part("day")}`, time: item.event_time?.slice(0, 5) || `${part("hour")}:${part("minute")}` };
}

function isoWeek(date: Date) {
  const thursday = new Date(date);
  thursday.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7));
  return Math.ceil(((thursday.getTime() - Date.UTC(thursday.getUTCFullYear(), 0, 1, 12)) / 86400000 + 1) / 7);
}

export function activityOccurrences(activity: OverviewActivity, today: string): OverviewEvent[] {
  const date = calendarDate(today);
  if (!date || !activity.schedule || (activity.paused_until && activity.paused_until.slice(0, 10) >= today)) return [];
  const schedule = activity.schedule.toLocaleLowerCase("nb-NO");
  // Free-text exceptions/ranges need a dated calendar/Spond event, not a guessed recurrence.
  if (/\d{4}-\d{2}-\d{2}|\b(unntatt|ferie|pause|avlyst|måned|månedlig|første|andre|tredje|siste|etter avtale)\b|\b(?:uke|hver)\s*\d/.test(schedule)) return [];
  if (/annenhver/.test(schedule)) {
    if (!/odde|partall/.test(schedule)) return [];
    if ((isoWeek(date) % 2 === 1) !== /odde/.test(schedule)) return [];
  }
  const matches = [...schedule.matchAll(/(mandag|tirsdag|onsdag|torsdag|fredag|lørdag|søndag)(?:er)?\b/g)];
  if (matches.some((match, i) => i > 0 && /^\s*[-–/]\s*$/.test(schedule.slice(matches[i - 1].index! + matches[i - 1][0].length, match.index)))) return [];
  return matches.flatMap((match, index) => {
    if (match[1] !== days[date.getUTCDay()]) return [];
    const clause = schedule.slice(match.index! + match[0].length, matches[index + 1]?.index);
    const clock = clause.match(/\b(\d{1,2})[:.](\d{2})\b/);
    if (clock && (Number(clock[1]) > 23 || Number(clock[2]) > 59)) return [];
    const time = clock ? `${clock[1].padStart(2, "0")}:${clock[2]}` : null;
    return [{ id: `activity-${activity.id}-${today}-${index}`, title: activity.name, event_date: today, event_time: time, location: activity.location, member_id: activity.member_id, member: activity.member }];
  });
}

function titleMatches(activity: OverviewActivity, event: OverviewEvent) {
  const name = normalized(activity.name), title = normalized(event.title);
  if (name === title || title.startsWith(`${name} `) || name.startsWith(`${title} `)) return true;
  // Parenthesized schedule labels, e.g. “torsdag (samspill)”, can identify a dated session.
  const labels = [...(activity.schedule || "").matchAll(/\(([^)]+)\)/g)].map(match => normalized(match[1]));
  return labels.some(label => label.length >= 4 && (` ${title} `).includes(` ${label} `));
}

export function upcomingOverview(data: { date: string; family?: { timezone?: string }; events: OverviewEvent[]; spond_events: OverviewEvent[]; activities: OverviewActivity[] }) {
  const today = calendarDate(data.date);
  if (!today) return [];
  const end = new Date(today);
  end.setUTCDate(end.getUTCDate() + overviewSettings.datedDays - 1);
  const endDate = end.toISOString().slice(0, 10);
  const zone = data.family?.timezone || "Europe/Oslo";
  const dated = [...data.spond_events, ...data.events].map(item => {
    const parts = occurrenceParts(item, zone);
    return { ...item, event_date: parts.date, event_time: parts.time };
  }).filter(item => calendarDate(item.event_date) && item.event_date >= data.date && item.event_date <= endDate);
  const identity = (item: OverviewEvent) => JSON.stringify([normalized(item.title), item.member_id ?? null, item.event_date]);
  const times = new Map<string, Set<string>>();
  for (const item of dated) {
    if (!item.event_time) continue;
    const key = identity(item);
    if (!times.has(key)) times.set(key, new Set());
    times.get(key)!.add(item.event_time);
  }
  const datedSeen = new Set<string>();
  const unique = dated.filter(item => {
    if (!item.event_time && times.get(identity(item))?.size === 1) return false;
    const key = JSON.stringify([identity(item), item.event_time || ""]);
    if (datedSeen.has(key)) return false;
    datedSeen.add(key); return true;
  });
  const routines = data.activities.flatMap(activity => activityOccurrences(activity, data.date).filter(routine =>
    !unique.some(event => event.member_id === routine.member_id && event.event_date === routine.event_date
      && (!routine.event_time || !event.event_time || routine.event_time === event.event_time)
      && titleMatches(activity, event))));
  const seen = new Set<string>();
  return [...unique, ...routines].filter(item => {
    const key = JSON.stringify([normalized(item.title), item.member_id ?? null, item.event_date, item.event_time || ""]);
    if (seen.has(key)) return false;
    seen.add(key); return true;
  }).sort((a, b) => a.event_date.localeCompare(b.event_date) || (a.event_time || "").localeCompare(b.event_time || "") || a.title.localeCompare(b.title)).slice(0, overviewSettings.maxItems);
}

export function weatherKind(symbol?: string | null) {
  const code = (symbol || "").toLowerCase().split("_")[0];
  if (!/^(clearsky|fair|partlycloudy|cloudy|fog|(?:light|heavy)?(?:rain|sleet|snow)(?:showers)?(?:andthunder)?)$/.test(code)) return "unknown";
  if (code.includes("thunder")) return "thunder";
  if (code.includes("sleet")) return "sleet";
  if (code.includes("snow")) return "snow";
  if (code.includes("rain")) return "rain";
  if (code === "fog") return "fog";
  if (code === "clearsky") return symbol?.endsWith("_night") ? "night" : "sun";
  if (code === "fair" || code === "partlycloudy") return "partlycloudy";
  return "cloudy";
}
