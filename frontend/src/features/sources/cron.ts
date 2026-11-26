/**
 * Human-readable schedules over 5-field cron (the stored form). Presets build a cron string;
 * `parsePreset` recognises them again; `nextRuns` computes upcoming times in a time zone.
 */
export type Preset =
  | { mode: "daily"; time: string }
  | { mode: "weekdays"; time: string }
  | { mode: "hours"; every: number }
  | { mode: "cron"; cron: string }

const pad = (n: number) => String(n).padStart(2, "0")

export function presetToCron(p: Preset): string {
  if (p.mode === "cron") return p.cron.trim()
  if (p.mode === "hours") return `0 */${p.every} * * *`
  const [h, m] = p.time.split(":").map(Number)
  return `${m} ${h} * * ${p.mode === "weekdays" ? "1-5" : "*"}`
}

export function parsePreset(cron: string): Preset {
  const c = cron.trim().replace(/\s+/g, " ")
  let m = /^(\d{1,2}) (\d{1,2}) \* \* (\*|1-5)$/.exec(c)
  if (m && Number(m[1]) < 60 && Number(m[2]) < 24)
    return {
      mode: m[3] === "*" ? "daily" : "weekdays",
      time: `${pad(Number(m[2]))}:${pad(Number(m[1]))}`,
    }
  m = /^0 \*\/(\d{1,2}) \* \* \*$/.exec(c)
  if (m && Number(m[1]) >= 1 && Number(m[1]) <= 23)
    return { mode: "hours", every: Number(m[1]) }
  return { mode: "cron", cron: c }
}

/** A sentence for a schedule, e.g. "Every weekday at 07:30". */
export function describeCron(cron: string): string {
  const p = parsePreset(cron)
  if (p.mode === "daily") return `Every day at ${p.time}`
  if (p.mode === "weekdays") return `Every weekday at ${p.time}`
  if (p.mode === "hours")
    return p.every === 1 ? "Every hour" : `Every ${p.every} hours`
  return fields(p.cron) ? `Custom: ${p.cron}` : "Custom schedule"
}

type Parsed = {
  min: Set<number>
  hour: Set<number>
  dom: Set<number>
  mon: Set<number>
  dow: Set<number>
  domAny: boolean
  dowAny: boolean
}

function expand(part: string, lo: number, hi: number): Set<number> | null {
  const out = new Set<number>()
  for (const piece of part.split(",")) {
    const [range, stepRaw] = piece.split("/")
    const step = stepRaw === undefined ? 1 : Number(stepRaw)
    if (!Number.isInteger(step) || step < 1) return null
    let a: number
    let b: number
    if (range === "*") {
      a = lo
      b = hi
    } else if (/^\d+$/.test(range)) {
      a = Number(range)
      b = stepRaw === undefined ? a : hi
    } else {
      const m = /^(\d+)-(\d+)$/.exec(range)
      if (!m) return null
      a = Number(m[1])
      b = Number(m[2])
    }
    if (a < lo || b > hi || a > b) return null
    for (let i = a; i <= b; i += step) out.add(i)
  }
  return out
}

function fields(cron: string): Parsed | null {
  const f = cron.trim().split(/\s+/)
  if (f.length !== 5) return null
  const min = expand(f[0], 0, 59)
  const hour = expand(f[1], 0, 23)
  const dom = expand(f[2], 1, 31)
  const mon = expand(f[3], 1, 12)
  const dow = expand(f[4].replace(/\b7\b/g, "0"), 0, 6)
  if (!min || !hour || !dom || !mon || !dow) return null
  return {
    min,
    hour,
    dom,
    mon,
    dow,
    domAny: f[2] === "*",
    dowAny: f[4] === "*",
  }
}

/** Null when the expression is valid, else a plain-words reason. */
export function validateCron(cron: string): string | null {
  const n = cron.trim().split(/\s+/).filter(Boolean).length
  if (n !== 5)
    return "Use five fields: minute, hour, day of month, month, day of week."
  return fields(cron) ? null : "One of the fields is out of range or malformed."
}

const dtfCache = new Map<string, Intl.DateTimeFormat>()
function parts(ms: number, tz: string) {
  let f = dtfCache.get(tz)
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
    })
    dtfCache.set(tz, f)
  }
  const o: Record<string, number> = {}
  for (const p of f.formatToParts(new Date(ms)))
    if (p.type !== "literal") o[p.type] = Number(p.value)
  return o
}

function offsetAt(ms: number, tz: string) {
  const p = parts(ms, tz)
  return (
    Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) -
    Math.floor(ms / 60000) * 60000
  )
}

/** UTC instant (ms) of a wall-clock time in a zone; null when that time does not exist. */
function zonedToUtc(
  y: number,
  mo: number,
  d: number,
  h: number,
  mi: number,
  tz: string
): number | null {
  const guess = Date.UTC(y, mo - 1, d, h, mi)
  for (const off of [0, 1, -1]) {
    const t = guess - (offsetAt(guess, tz) + off * 3_600_000)
    const p = parts(t, tz)
    if (
      p.year === y &&
      p.month === mo &&
      p.day === d &&
      p.hour === h &&
      p.minute === mi
    )
      return t
  }
  return null
}

/** The next `count` run times after `from`, in the given time zone. */
export function nextRuns(
  cron: string,
  tz: string,
  count = 3,
  from: Date = new Date()
): Date[] {
  const f = fields(cron)
  if (!f) return []
  const out: Date[] = []
  const start = parts(from.getTime(), tz)
  const day = new Date(Date.UTC(start.year, start.month - 1, start.day))
  const hours = [...f.hour].sort((a, b) => a - b)
  const mins = [...f.min].sort((a, b) => a - b)
  for (let i = 0; i < 800 && out.length < count; i++) {
    const y = day.getUTCFullYear()
    const mo = day.getUTCMonth() + 1
    const d = day.getUTCDate()
    const dow = day.getUTCDay()
    day.setUTCDate(d + 1)
    if (!f.mon.has(mo)) continue
    const domOk = f.dom.has(d)
    const dowOk = f.dow.has(dow)
    // Standard cron: when both day fields are restricted, either may match.
    const dayOk =
      f.domAny || f.dowAny
        ? (f.domAny || domOk) && (f.dowAny || dowOk)
        : domOk || dowOk
    if (!dayOk) continue
    for (const h of hours)
      for (const m of mins) {
        const t = zonedToUtc(y, mo, d, h, m, tz)
        if (t !== null && t > from.getTime()) {
          out.push(new Date(t))
          if (out.length >= count) return out
        }
      }
  }
  return out
}

export function formatWhen(d: Date | string, tz: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(typeof d === "string" ? new Date(d) : d)
}
