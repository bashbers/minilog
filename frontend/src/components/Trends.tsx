import type { TimelineRecord } from "../api/types";
import { careRecordSummaryValues, careSummaryCatalog } from "../careRecordForms";

export function Trends({ records }: { records: TimelineRecord[] }) {
  return (
    <div className="trend-grid">
      {careSummaryCatalog.map((metric) => {
        const values = Array.from({ length: 7 }, (_, offset) => {
          const date = new Date();
          date.setHours(0, 0, 0, 0);
          date.setDate(date.getDate() - (6 - offset));
          const next = new Date(date);
          next.setDate(next.getDate() + 1);
          return records
            .filter((record) => {
              const timestamp = new Date(record.occurred_at);
              return timestamp >= date && timestamp < next;
            })
            .reduce(
              (sum, record) => sum + careRecordSummaryValues(record)
                .filter((summary) => summary.key === metric.key)
                .reduce((recordSum, summary) => recordSum + summary.value, 0),
              0,
            );
        });
        const maximum = Math.max(...values, 1);
        const total = values.reduce((sum, value) => sum + value, 0);
        return (
          <section className="trend-card" key={metric.label}>
            <div><p className="eyebrow">Last 7 days</p><h2>{metric.label}</h2></div>
            <strong className="trend-total">{Math.round(total)} <span>{metric.suffix}</span></strong>
            <div className="bar-chart" aria-label={`${metric.label} over seven days`}>
              {values.map((value, index) => <div className="bar-slot" key={index}><div className="bar" style={{ height: `${Math.max(4, (value / maximum) * 100)}%` }} /><span>{new Intl.DateTimeFormat(undefined, { weekday: "narrow" }).format(new Date(Date.now() - (6 - index) * 86_400_000))}</span></div>)}
            </div>
          </section>
        );
      })}
      <p className="trend-disclaimer">Charts summarize what caregivers entered. They do not assess health or development.</p>
    </div>
  );
}
