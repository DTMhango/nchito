import { describe, expect, it } from "vitest"
import { costOf, formatCost, microsOf } from "./cost"

describe("formatCost", () => {
  it("shows cents and up with two decimals", () => {
    expect(formatCost(1_240_000)).toBe("$1.24")
    expect(formatCost(10_000)).toBe("$0.01")
    expect(formatCost(0)).toBe("$0.00")
    expect(formatCost(null)).toBe("$0.00")
  })
  it("shows sub-cent amounts by their significant digits", () => {
    expect(formatCost(4_000)).toBe("$0.004")
    expect(formatCost(350)).toBe("$0.00035")
    expect(formatCost(1)).toBe("$0.000001")
  })
  it("says under a cent in compact spaces", () => {
    expect(formatCost(4_000, { compact: true })).toBe("under $0.01")
    expect(formatCost(25_000, { compact: true })).toBe("$0.03")
  })
})

describe("microsOf", () => {
  it("prefers micros and falls back to minor", () => {
    expect(microsOf({ cost_micros: 4_200, cost_minor: 0 }, "cost")).toBe(4_200)
    expect(microsOf({ cost_minor: 3 }, "cost")).toBe(30_000)
    expect(microsOf({}, "cost")).toBeNull()
    expect(costOf({ cap_minor: null }, "cap")).toBe("—")
  })
})
