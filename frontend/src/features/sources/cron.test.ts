import { describe, expect, it } from "vitest"
import {
  describeCron,
  formatWhen,
  nextRuns,
  parsePreset,
  presetToCron,
  validateCron,
} from "./cron"

const from = new Date("2026-11-26T10:00:00Z") // Thursday 12:00 in Lusaka (UTC+2)

describe("cron presets", () => {
  it("round-trips presets", () => {
    for (const cron of ["30 7 * * *", "30 7 * * 1-5", "0 */6 * * *"])
      expect(presetToCron(parsePreset(cron))).toBe(cron)
  })
  it("falls back to advanced for anything else", () => {
    expect(parsePreset("*/15 9-17 * * 1,3").mode).toBe("cron")
  })
  it("describes in words", () => {
    expect(describeCron("30 7 * * 1-5")).toBe("Every weekday at 07:30")
    expect(describeCron("0 */4 * * *")).toBe("Every 4 hours")
  })
  it("validates", () => {
    expect(validateCron("0 7 * * *")).toBeNull()
    expect(validateCron("0 7 * *")).toMatch(/five fields/)
    expect(validateCron("0 25 * * *")).toMatch(/out of range/)
  })
})

describe("nextRuns", () => {
  it("finds the next three daily runs in the zone", () => {
    const r = nextRuns("30 7 * * *", "Africa/Lusaka", 3, from)
    expect(r.map((d) => d.toISOString())).toEqual([
      "2026-11-27T05:30:00.000Z",
      "2026-11-28T05:30:00.000Z",
      "2026-11-29T05:30:00.000Z",
    ])
  })
  it("skips weekends for weekdays", () => {
    const r = nextRuns("0 8 * * 1-5", "Africa/Lusaka", 3, from)
    expect(r.map((d) => d.toISOString().slice(0, 10))).toEqual([
      "2026-11-27",
      "2026-11-30",
      "2026-12-01",
    ])
  })
  it("handles every N hours", () => {
    const r = nextRuns("0 */6 * * *", "Africa/Lusaka", 3, from)
    expect(formatWhen(r[0], "Africa/Lusaka")).toContain("18:00")
    expect(r).toHaveLength(3)
  })
  it("returns nothing for invalid cron", () => {
    expect(nextRuns("nope", "UTC")).toEqual([])
  })
})
