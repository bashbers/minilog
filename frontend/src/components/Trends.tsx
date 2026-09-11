import type { TimelineRecord } from "../api/types";
import { careRecordSummaryValues, careSummaryCatalog } from "../careRecordForms";
import { dateKeyInTimeZone, formatDateKey, shiftDateKey } from "../lib/time";

type TrendDays = 1 | 7 | 30;

interface TrendsProps {
  records: TimelineRecord[];
  timeZone: string;
  days: TrendDays;
  onDaysChange: (days: TrendDays) => void;
}

function rangeLabel(days: TrendDays) {
  return days === 1 ? "Today" : `Last ${days} days`;
}

function TrendBars({
  label,
  dateKeys,
  values,
  days,
}: {
  label: string;
  dateKeys: string[];
  values: number[];
  days: TrendDays;
}) {
  const maximum = Math.max(...values, 1);
  return <div className={`bar-chart days-${days}`} aria-label={`${label} for ${rangeLabel(days).toLowerCase()}`}>
    {values.map((value, index) => <div className="bar-slot" key={dateKeys[index]} title={`${dateKeys[index]}: ${value}`}>
      <div className="bar" style={{ height: `${Math.max(4, (value / maximum) * 100)}%` }} />
      <span>{days === 30 && index % 5 !== 0 && index !== 29 ? "" : formatDateKey(dateKeys[index], days === 1 ? { weekday: "short" } : { weekday: "narrow" })}</span>
    </div>)}
  </div>;
}

export function Trends({ records, timeZone, days, onDaysChange }: TrendsProps) {
  const todayKey = dateKeyInTimeZone(new Date(), timeZone);
  const dateKeys = Array.from({ length: days }, (_, offset) =>
    shiftDateKey(todayKey, offset - days + 1));
  const measurements = records.filter(
    (record): record is Extract<TimelineRecord, { record_type: "measurement" }> =>
      record.record_type === "measurement",
  );
  const measurementSeries = Array.from(new Set(
    measurements.map((record) => `${record.details.kind}|${record.details.entered_unit}`),
  )).map((series) => {
    const [kind, unit] = series.split("|");
    const matching = measurements.filter((record) =>
      record.details.kind === kind && record.details.entered_unit === unit);
    const values = dateKeys.map((dateKey) => {
      const record = matching.find((item) =>
        dateKeyInTimeZone(item.occurred_at, timeZone) === dateKey);
      return record ? Number(record.details.entered_value) : 0;
    });
    return { series, kind, unit, values, latest: matching[0] };
  });

  return <>
    <div className="range-switcher" aria-label="Trend period">
      {([1, 7, 30] as const).map((period) => <button key={period} type="button" aria-pressed={days === period} onClick={() => onDaysChange(period)}>{period === 1 ? "Daily" : `${period} days`}</button>)}
    </div>
    <div className="trend-grid">
      {careSummaryCatalog.map((metric) => {
        const values = dateKeys.map((dateKey) => records
          .filter((record) => dateKeyInTimeZone(record.occurred_at, timeZone) === dateKey)
          .reduce(
            (sum, record) => sum + careRecordSummaryValues(record)
              .filter((summary) => summary.key === metric.key)
              .reduce((recordSum, summary) => recordSum + summary.value, 0),
            0,
          ));
        const total = values.reduce((sum, value) => sum + value, 0);
        return <section className="trend-card" key={metric.label}>
          <div><p className="eyebrow">{rangeLabel(days)}</p><h2>{metric.label}</h2></div>
          <strong className="trend-total">{Math.round(total)} <span>{metric.suffix}</span></strong>
          <TrendBars label={metric.label} dateKeys={dateKeys} values={values} days={days} />
        </section>;
      })}
      {measurementSeries.map(({ series, kind, unit, values, latest }) => <section className="trend-card" key={series}>
        <div><p className="eyebrow">{rangeLabel(days)} · entered values</p><h2>{kind[0].toUpperCase() + kind.slice(1)}</h2></div>
        <strong className="trend-total">{latest ? Number(latest.details.entered_value) : "—"} <span>{unit}</span></strong>
        <TrendBars label={`${kind} in ${unit}`} dateKeys={dateKeys} values={values} days={days} />
      </section>)}
      <p className="trend-disclaimer">Charts summarize what caregivers entered. They do not assess health or development.</p>
    </div>
  </>;
}
