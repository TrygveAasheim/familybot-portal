import assert from "node:assert/strict";
import test from "node:test";
import { activityOccurrences, occurrenceParts, overviewSettings, upcomingOverview, weatherKind } from "../app/_components/dashboardOverview.ts";

const activity = { id: 1, name: "Musikk", member_id: 3, member: "Ada", schedule: "Tirsdager 17:00, torsdager 18:30" };
const event = (extra = {}) => ({ id: 2, title: "Musikk", event_date: "2026-11-10", event_time: "17:00", member_id: 3, ...extra });
const data = (extra = {}) => ({ date: "2026-11-10", family: { timezone: "Europe/Oslo" }, events: [], spond_events: [], activities: [], ...extra });

test("recurring activities appear only on the matching household day with that day's time", () => {
  assert.equal(activityOccurrences(activity, "2026-11-10")[0].event_time, "17:00");
  assert.equal(activityOccurrences(activity, "2026-11-12")[0].event_time, "18:30");
  assert.deepEqual(activityOccurrences(activity, "2026-11-11"), []);
  assert.equal(upcomingOverview(data({ activities: [activity] })).length, 1);
  assert.deepEqual(upcomingOverview(data({ date: "2026-11-11", activities: [activity] })), []);
});

test("pause is inclusive; missing, ambiguous and invalid schedules are not guessed", () => {
  assert.deepEqual(activityOccurrences({ ...activity, paused_until: "2026-11-10" }, "2026-11-10"), []);
  assert.equal(activityOccurrences({ ...activity, paused_until: "2026-11-09" }, "2026-11-10").length, 1);
  for (const schedule of [null, "Etter avtale", "Annenhver tirsdag", "Mandag–fredag", "Tirsdag 25:60", "Tirsdag unntatt ferie", "Tirsdag 2026-11-17", "Første tirsdag i måneden", "Tirsdag hver 3. uke"]) {
    assert.deepEqual(activityOccurrences({ ...activity, schedule }, "2026-11-10"), [], String(schedule));
  }
  assert.equal(activityOccurrences({ ...activity, schedule: "Tirsdag (samspill)" }, "2026-11-10")[0].event_time, null);
  assert.deepEqual(activityOccurrences(activity, "2026-02-30"), []);
});

test("explicit alternate-week parity is respected across the new year", () => {
  assert.equal(activityOccurrences({ ...activity, schedule: "Annenhver tirsdag, oddetallsuker 17:00" }, "2026-11-10").length, 0);
  assert.equal(activityOccurrences({ ...activity, schedule: "Annenhver tirsdag, partallsuker 17:00" }, "2026-11-10").length, 1);
  assert.equal(activityOccurrences({ ...activity, schedule: "Annenhver fredag, oddetallsuker 17:00" }, "2027-01-01").length, 1);
});

test("dated source takes precedence over duplicate sources and a recurring activity", () => {
  const result = upcomingOverview(data({ activities: [activity], events: [event()], spond_events: [event({ id: "spond", title: "  MUSIKK! " })] }));
  assert.equal(result.length, 1);
  assert.equal(result[0].id, "spond");
  assert.equal(upcomingOverview(data({ events: [event(), event({ id: 4, event_time: null })], spond_events: [event({ id: "s" })] })).length, 1);
  assert.equal(upcomingOverview(data({ activities: [{ ...activity, schedule: "Tirsdag (samspill)" }], events: [event({ title: "Samspill ungdomsorkester" })] })).length, 1);
});

test("different members, times or unrelated activities are never collapsed", () => {
  const result = upcomingOverview(data({ events: [event(), event({ id: 3, member_id: 4 }), event({ id: 4, event_time: "19:00" }), event({ id: 5, title: "Svømming" })] }));
  assert.equal(result.length, 4);
  assert.equal(upcomingOverview(data({ activities: [activity], events: [event({ event_time: "19:00" })] })).length, 2);
});

test("five-day boundary, cross-year date arithmetic and bounded sorting", () => {
  const result = upcomingOverview(data({ date: "2026-12-30", events: [event({ event_date: "2027-01-03" }), event({ event_date: "2027-01-04" }), event({ event_date: "2026-12-29" })] }));
  assert.deepEqual(result.map(item => item.event_date), ["2027-01-03"]);
  assert.equal(upcomingOverview(data({ events: Array.from({ length: 8 }, (_, id) => event({ id, title: `Event ${id}` })) })).length, 4);
  assert.deepEqual(upcomingOverview(data({ date: "bad" })), []);
  assert.equal(overviewSettings.showActivitiesCard, false);
});

test("household timezone, midnight and DST normalize timestamp events before deduplication", () => {
  assert.deepEqual(occurrenceParts(event({ event_date: "2026-11-09T23:30:00Z", event_time: null }), "Europe/Oslo"), { date: "2026-11-10", time: "00:30" });
  assert.deepEqual(occurrenceParts(event({ event_date: "2026-03-29T01:30:00Z", event_time: null }), "Europe/Oslo"), { date: "2026-03-29", time: "03:30" });
  assert.equal(upcomingOverview(data({ events: [event()], spond_events: [event({ id: "s", event_date: "2026-11-10T16:00:00Z", event_time: null })] })).length, 1);
  assert.deepEqual(occurrenceParts(event({ event_date: "invalidZ" }), "Europe/Oslo"), { date: "", time: "" });
});

test("forecast symbols cover clear, mixed, hazardous and unavailable weather", () => {
  for (const [code, expected] of [["clearsky_day", "sun"], ["clearsky_night", "night"], ["fair_day", "partlycloudy"], ["partlycloudy", "partlycloudy"], ["cloudy", "cloudy"], ["fog", "fog"], ["heavyrain", "rain"], ["lightsnowshowers_day", "snow"], ["sleet", "sleet"], ["heavyrainandthunder", "thunder"], [null, "unknown"], ["unrecognized", "unknown"]]) {
    assert.equal(weatherKind(code), expected);
  }
});
