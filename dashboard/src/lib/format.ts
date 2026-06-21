// Money is stored as integer kopecks (₽×100) everywhere in the bot.
export function fmtRub(kopecks: number | null | undefined): string {
  const rub = Math.round((kopecks ?? 0) / 100);
  return new Intl.NumberFormat("ru-RU").format(rub) + " ₽";
}

export function fmtNum(n: number | null | undefined): string {
  return new Intl.NumberFormat("ru-RU").format(n ?? 0);
}

export function fmtCompactInt(n: number | null | undefined): string {
  return new Intl.NumberFormat("ru-RU", { notation: "compact" }).format(n ?? 0);
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  return (n ?? 0).toFixed(digits) + "%";
}

const MSK = "Europe/Moscow";

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit", timeZone: MSK,
  });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: MSK,
  });
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.round(diff / 1000);
  if (s < 60) return "только что";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} мин назад`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} ч назад`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} дн назад`;
  return fmtDate(iso);
}

export function dayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "2-digit", month: "short", timeZone: MSK,
  });
}
