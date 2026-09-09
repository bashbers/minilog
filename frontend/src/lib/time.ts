export function localDateTimeValue(date = new Date()) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

export function toTimestamp(value: string) {
  return new Date(value).toISOString();
}

export function localOffsetMinutes(value: string) {
  return -new Date(value).getTimezoneOffset();
}

export function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(
    new Date(value),
  );
}

export function formatDay(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export function durationMinutes(start: string, end: string | null) {
  const endTime = end ? new Date(end).getTime() : Date.now();
  return Math.max(0, Math.round((endTime - new Date(start).getTime()) / 60_000));
}

