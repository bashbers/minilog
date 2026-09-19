type DisplayPreferences = {
  locale: string;
  timeZone: string;
  clockFormat: "12h" | "24h";
  measurementSystem: "metric" | "imperial";
};

let displayPreferences: DisplayPreferences = {
  locale: navigator.language,
  timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  clockFormat: "24h",
  measurementSystem: "metric",
};

export function configureDisplayPreferences(preferences: DisplayPreferences) {
  displayPreferences = preferences;
}

function formatter(options: Intl.DateTimeFormatOptions) {
  try {
    return new Intl.DateTimeFormat(displayPreferences.locale, options);
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
    return new Intl.DateTimeFormat(undefined, options);
  }
}

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
  return formatter({
    hour: "2-digit",
    minute: "2-digit",
    hour12: displayPreferences.clockFormat === "12h",
    timeZone: displayPreferences.timeZone,
  }).format(
    new Date(value),
  );
}

export function formatDay(value: string) {
  return formatter({
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: displayPreferences.timeZone,
  }).format(new Date(value));
}

export function formatToday() {
  return formatter({
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: displayPreferences.timeZone,
  }).format(new Date());
}

export function defaultMeasurementUnit(kind: "weight" | "height" | "temperature") {
  const metric = { weight: "kg", height: "cm", temperature: "celsius" } as const;
  const imperial = { weight: "lb", height: "in", temperature: "fahrenheit" } as const;
  return (displayPreferences.measurementSystem === "imperial" ? imperial : metric)[kind];
}

export function durationMinutes(start: string, end: string | null) {
  const endTime = end ? new Date(end).getTime() : Date.now();
  return Math.max(0, Math.round((endTime - new Date(start).getTime()) / 60_000));
}

export function dateKeyInTimeZone(
  value: Date | string,
  timeZone: string,
): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(typeof value === "string" ? new Date(value) : value);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function shiftDateKey(dateKey: string, days: number): string {
  const date = new Date(`${dateKey}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function formatDateKey(dateKey: string, options: Intl.DateTimeFormatOptions) {
  return formatter({ ...options, timeZone: "UTC" }).format(
    new Date(`${dateKey}T12:00:00Z`),
  );
}
