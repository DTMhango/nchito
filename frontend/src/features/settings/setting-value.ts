/** Pure helpers for the generic settings renderer: draft <-> value, client-side validation. */
import type { SettingOut } from "./api"

export type Draft = string | boolean | string[]

/**
 * A list setting with fixed choices shows checkboxes; one without shows one item per line (items
 * such as phrases and patterns may themselves hold commas).
 */
export const isChoiceList = (s: SettingOut) =>
  s.kind === "list" && !!s.choices?.length

export function toDraft(s: SettingOut, value: unknown = s.value): Draft {
  if (s.kind === "bool") return value === true
  if (s.kind === "list") {
    const items = Array.isArray(value) ? value.map(String) : []
    return isChoiceList(s) ? items : items.join("\n")
  }
  return value === null || value === undefined ? "" : String(value)
}

export type Parsed = { ok: true; value: unknown } | { ok: false; error: string }

const NUMERIC = new Set(["int", "float", "money_minor"])

/** Turn what the owner typed into the value to send, or say what is wrong in plain words. */
export function parseDraft(s: SettingOut, draft: Draft): Parsed {
  if (s.kind === "bool") return { ok: true, value: draft === true }
  if (s.kind === "list") {
    const items = Array.isArray(draft)
      ? draft
      : String(draft)
          .split(/\r?\n/)
          .map((x) => x.trim())
          .filter(Boolean)
    const bad = s.choices?.length
      ? items.find((i) => !s.choices!.includes(i))
      : undefined
    if (bad) return { ok: false, error: `"${bad}" is not an option.` }
    return { ok: true, value: items }
  }
  const text = String(draft).trim()
  if (text === "") {
    return s.nullable
      ? { ok: true, value: null }
      : { ok: false, error: "Enter a value." }
  }
  if (NUMERIC.has(s.kind)) {
    const n = Number(text)
    if (!Number.isFinite(n)) return { ok: false, error: "Enter a number." }
    if (s.kind !== "float" && !Number.isInteger(n))
      return { ok: false, error: "Use a whole number." }
    if (s.minimum != null && n < s.minimum)
      return { ok: false, error: `Must be at least ${s.minimum}.` }
    if (s.maximum != null && n > s.maximum)
      return { ok: false, error: `Must be at most ${s.maximum}.` }
    return { ok: true, value: n }
  }
  if (s.kind === "enum" && s.choices && !s.choices.includes(text))
    return { ok: false, error: "Pick one of the options." }
  if (s.kind === "time" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(text))
    return { ok: false, error: "Use a time like 21:00." }
  if (s.kind === "cron" && text.split(/\s+/).length !== 5)
    return {
      ok: false,
      error: "Use five fields, like 0 6 * * * (minute hour day month weekday).",
    }
  return { ok: true, value: text }
}

/** A value as the owner reads it ("60 points", "Off", "21:00"), for defaults and history. */
export function displayValue(s: SettingOut, value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not set"
  if (typeof value === "boolean") return value ? "On" : "Off"
  if (Array.isArray(value)) return value.length ? value.join(", ") : "None"
  const label = String(value)
  return s.unit && typeof value === "number" ? `${label} ${s.unit}` : label
}

export const sameValue = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b)
