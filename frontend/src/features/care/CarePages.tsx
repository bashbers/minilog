import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../../api/client";
import type { Baby, TimelineRecord } from "../../api/types";
import {
  careActions,
  careRecordSummaryValues,
  careRecordTypesForGroup,
  careSummaryCatalog,
  isActiveCareRecord,
} from "../../careRecordForms";
import { Timeline } from "../../components/Timeline";
import { Trends } from "../../components/Trends";
import { useRecords } from "../../hooks/useRecords";
import { dateKeyInTimeZone, formatDateKey, formatToday, shiftDateKey } from "../../lib/time";

export function TodayPage({ baby, timeZone }: { baby: Baby; timeZone: string }) {
  const recentRecords = useRecords(baby.id);
  const todayKey = dateKeyInTimeZone(new Date(), timeZone);
  const dayRecords = useQuery({
    queryKey: ["today-records", baby.id, todayKey],
    queryFn: () => api.allRecords(baby.id, { dateFrom: todayKey, dateTo: todayKey }),
  });
  const activeRecords = useQuery({
    queryKey: ["active-records", baby.id],
    queryFn: () => api.allRecords(baby.id, { activeOnly: true }),
    refetchInterval: 5_000,
  });
  const today = useMemo(() => {
    const now = Date.now();
    const queued = (recentRecords.data ?? []).filter((record) => record.queued);
    const persisted = dayRecords.data ?? (recentRecords.data ?? []).filter((record) => !record.queued);
    const combined = [...queued, ...persisted, ...(activeRecords.data ?? [])];
    return [...new Map(combined.map((record) => [record.id, record])).values()]
      .filter((record) => isActiveCareRecord(record) || (
        dateKeyInTimeZone(record.occurred_at, timeZone) === todayKey
        && new Date(record.occurred_at).getTime() <= now
      ))
      .sort((left, right) => new Date(right.occurred_at).getTime() - new Date(left.occurred_at).getTime());
  }, [activeRecords.data, dayRecords.data, recentRecords.data, timeZone, todayKey]);
  const active = today.filter(isActiveCareRecord);
  return <main className="page">
    <div className="page-heading"><div><p className="eyebrow">{formatToday()}</p><h1>{active.length ? `${active.length} active now` : "Today's care"}</h1></div><span className={`status-pill ${navigator.onLine ? "online" : "offline"}`}>{navigator.onLine ? "Synced" : "Offline"}</span></div>
    <DailySummary records={today} />
    {recentRecords.isLoading && dayRecords.isLoading ? <div className="skeleton-list" /> : <Timeline records={today} babyId={baby.id} />}
  </main>;
}

export function HistoryPage({ baby }: { baby: Baby }) {
  const [filter, setFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const recordTypes: TimelineRecord["record_type"][] | undefined = filter === "all"
    ? undefined
    : filter === "feeding"
      ? careRecordTypesForGroup("feeding")
      : [filter as TimelineRecord["record_type"]];
  const history = useInfiniteQuery({
    queryKey: ["history-records", baby.id, filter, dateFrom, dateTo],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.records(baby.id, {
      cursor: pageParam,
      recordTypes,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      limit: 50,
    }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const visible = history.data?.pages.flatMap((page) => page.items) ?? [];
  return <main className="page">
    <div className="page-heading"><div><p className="eyebrow">For {baby.display_name}</p><h1>History</h1></div></div>
    <div className="history-filters" aria-label="History filters">
      <label>Care type<select className="filter" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All care</option><option value="feeding">Feeding</option>{careActions.filter((action) => !careRecordTypesForGroup("feeding").includes(action.kind)).map((action) => <option value={action.kind} key={action.kind}>{action.label}</option>)}<option value="imported_care_record">Imported care record</option></select></label>
      <label>From<input type="date" value={dateFrom} max={dateTo || undefined} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label>To<input type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => setDateTo(event.target.value)} /></label>
    </div>
    {filter === "all" && <ImportedDailyNotes babyId={baby.id} dateFrom={dateFrom} dateTo={dateTo} />}
    {history.isPending ? <div className="skeleton-list" /> : <Timeline records={visible} babyId={baby.id} showDay />}
    {history.isError && <p className="error" role="alert">Could not load this history. Check the connection and try again.</p>}
    {history.hasNextPage && <button className="secondary load-older" disabled={history.isFetchingNextPage} onClick={() => history.fetchNextPage()}>{history.isFetchingNextPage ? "Loading…" : "Load older"}</button>}
  </main>;
}

function ImportedDailyNotes({ babyId, dateFrom, dateTo }: { babyId: string; dateFrom: string; dateTo: string }) {
  const notes = useQuery({
    queryKey: ["imported-daily-notes", babyId],
    queryFn: () => api.importedDailyNotes(babyId),
  });
  const visible = notes.data?.filter((note) => (!dateFrom || note.local_date >= dateFrom) && (!dateTo || note.local_date <= dateTo));
  if (!visible?.length) return null;
  return <section className="daily-notes" aria-label="Imported daily notes"><p className="eyebrow">PiyoLog daily notes</p>{visible.map((note) => <article key={note.id}><time>{formatDateKey(note.local_date, { dateStyle: "medium" })}</time><p>{note.body}</p></article>)}</section>;
}

export function TrendsPage({ baby, timeZone }: { baby: Baby; timeZone: string }) {
  const [days, setDays] = useState<1 | 7 | 30>(7);
  const todayKey = dateKeyInTimeZone(new Date(), timeZone);
  const dateFrom = shiftDateKey(todayKey, 1 - days);
  const records = useQuery({
    queryKey: ["trend-records", baby.id, dateFrom, todayKey],
    queryFn: () => api.allRecords(baby.id, { dateFrom, dateTo: todayKey }),
  });
  return <main className="page"><div className="page-heading"><div><p className="eyebrow">Patterns for {baby.display_name}</p><h1>Trends</h1></div></div><Trends records={records.data ?? []} timeZone={timeZone} days={days} onDaysChange={setDays} /></main>;
}

function DailySummary({ records }: { records: TimelineRecord[] }) {
  const summaryTotal = (key: string) => records.reduce((total, record) => total + careRecordSummaryValues(record).filter((summary) => summary.key === key).reduce((recordTotal, summary) => recordTotal + summary.value, 0), 0);
  const measurements = records.filter(
    (record): record is Extract<TimelineRecord, { record_type: "measurement" }> =>
      record.record_type === "measurement",
  ).filter((record, index, all) => all.findIndex((candidate) =>
    candidate.details.kind === record.details.kind
    && candidate.details.entered_unit === record.details.entered_unit) === index);
  return <section className="daily-summary" aria-label="Today's totals">
    {careSummaryCatalog.map((metric) => <div key={metric.key}><span>{metric.label}</span><strong>{Math.round(summaryTotal(metric.key))}{metric.suffix ? ` ${metric.suffix}` : ""}</strong></div>)}
    {measurements.map((record) => <div key={record.id}><span>Latest {record.details.kind}</span><strong>{Number(record.details.entered_value)} {record.details.entered_unit}</strong></div>)}
  </section>;
}
