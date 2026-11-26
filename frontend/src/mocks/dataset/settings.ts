/**
 * The mock settings registry: one store for every screen that reads or writes a setting
 * (Settings pages, Settings > AI, campaigns, sources, answers).
 *
 * `settings-registry.json` is a snapshot of the backend registry
 * (`backend/app/core/settings/registry.py`): keys, labels, kinds, defaults and bounds.
 * Refresh it with `npm run gen:mock-settings` when the registry changes.
 */
import type { Schemas } from "@/lib/api/types"
import registry from "./settings-registry.json"

export type SettingOut = Schemas["SettingOut"]
export type SettingRevision = Schemas["SettingRevisionOut"]

type Def = Omit<
  SettingOut,
  "value" | "is_default" | "version" | "updated_by" | "updated_at"
>

/** AI caps are stored in integer micros (1 USD = 1,000,000); the `_minor` caps retire. */
const RENAMED: Record<string, Partial<Def>> = {
  "budget.monthly_cap_minor": {
    key: "budget.monthly_cap_micros",
    description:
      "Monthly AI spend cap in micros. Unset means paid AI work stays off.",
    unit: "micros",
  },
  "budget.per_run_cap_minor": {
    key: "budget.per_run_cap_micros",
    description: "Spend cap per run in micros. Unset means no per-run cap.",
    unit: "micros",
  },
}

const MICROS_PER_MINOR = 10_000
const DEFS: Def[] = (registry.settings as Def[]).map((d) =>
  RENAMED[d.key]
    ? {
        ...d,
        ...RENAMED[d.key],
        minimum: d.minimum == null ? null : d.minimum * MICROS_PER_MINOR,
        maximum: d.maximum == null ? null : d.maximum * MICROS_PER_MINOR,
      }
    : d
)

export const SETTING_GROUPS: { key: string; label: string }[] = registry.groups

let rows: SettingOut[] = []
let history: Record<string, SettingRevision[]> = {}

export function resetSettingsStore() {
  rows = DEFS.map((d) => ({
    ...d,
    value: structuredClone(d.default),
    is_default: true,
    version: 0,
    updated_by: null,
    updated_at: null,
  }))
  history = {}
}
resetSettingsStore()

export const settingRows = () => rows
export const settingRow = (key: string) => rows.find((r) => r.key === key)
export const settingHistory = (key: string) => (history[key] ??= [])

/** Write a value as the owner, with a revision (the audit trail of a runtime setting). */
export function writeSetting(
  row: SettingOut,
  value: unknown,
  reason: string | null = null
) {
  const old = row.value
  row.value = value
  row.is_default = JSON.stringify(value) === JSON.stringify(row.default)
  row.version += 1
  row.updated_by = "owner"
  row.updated_at = new Date().toISOString()
  settingHistory(row.key).unshift({
    version: row.version,
    old_value: old,
    new_value: value,
    changed_by: "owner",
    changed_at: row.updated_at,
    reason,
  })
  return old
}

/**
 * Setting values by key, read and written in place (`settingValues["ai.provider"]`). Tests
 * and other mock areas use it to arrange state without going through HTTP.
 */
export const settingValues: Record<string, unknown> = new Proxy(
  {},
  {
    get: (_t, key) => settingRow(String(key))?.value,
    set: (_t, key, value) => {
      const row = settingRow(String(key))
      if (!row) return false
      row.value = value
      row.is_default = JSON.stringify(value) === JSON.stringify(row.default)
      return true
    },
    has: (_t, key) => !!settingRow(String(key)),
    ownKeys: () => rows.map((r) => r.key),
    getOwnPropertyDescriptor: (_t, key) =>
      settingRow(String(key))
        ? {
            enumerable: true,
            configurable: true,
            value: settingRow(String(key))?.value,
          }
        : undefined,
  }
)
