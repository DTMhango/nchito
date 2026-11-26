import { describe, expect, it } from "vitest"
import {
  contrastRatio,
  oklchToSrgb,
  parseLiteral,
  srgbToOklch,
  toHex,
} from "./colour"
import { contrastPairs, evaluateContrast, suggestFix } from "./contrast"
import { feColorMatrixValues, simulate, statusClashes } from "./cvd"
import { derivePalette } from "./derive"
import { BUILTIN_THEMES } from "./index"
import { GROUND_TOKENS, TOKEN_SPEC } from "./spec"
import { themeIssues, validTokenValue } from "./validate"

describe("contrast maths", () => {
  it.each([
    ["#000000", "#FFFFFF", 21],
    ["#FFFFFF", "#FFFFFF", 1],
    ["#777777", "#FFFFFF", 4.48],
    ["#767676", "#FFFFFF", 4.54],
    ["#595959", "#FFFFFF", 7.0],
    ["#0000FF", "#FFFFFF", 8.59],
    ["#FF0000", "#FFFFFF", 4.0],
    ["#00000080", "#FFFFFF", 4.0],
  ])("%s on %s is %s:1", (fg, bg, expected) => {
    expect(contrastRatio(parseLiteral(fg), parseLiteral(bg))).toBeCloseTo(
      expected,
      1
    )
  })

  it("converts OKLCH both ways", () => {
    const red = srgbToOklch(1, 0, 0)
    expect(red.l).toBeCloseTo(0.628, 3)
    expect(red.c).toBeCloseTo(0.258, 3)
    expect(red.h).toBeCloseTo(29.2, 1)
    expect(toHex(oklchToSrgb(red))).toBe("#FF0000")
  })

  it("derives pairs from the spec, body text on every ground", () => {
    const pairs = contrastPairs()
    for (const g of GROUND_TOKENS)
      expect(pairs).toContainEqual({ fg: "text", bg: g, use: "body" })
    const used = Object.keys(TOKEN_SPEC.tokens).filter(
      (k) => TOKEN_SPEC.tokens[k].use
    )
    expect(new Set(pairs.map((p) => p.fg))).toEqual(new Set(used))
  })

  it("finds no blocking pair in the built-ins and blocks dim body text", () => {
    for (const t of BUILTIN_THEMES)
      for (const mode of ["light", "dark"] as const)
        expect(
          evaluateContrast(t[mode], mode, t.chart, t.score).filter(
            (r) => r.blocking
          )
        ).toEqual([])
    const light = { ...BUILTIN_THEMES[0].light, text: "#BBBBBB" }
    const blocking = evaluateContrast(light, "light").filter((r) => r.blocking)
    expect(new Set(blocking.map((r) => r.fg))).toEqual(new Set(["text"]))
    const fix = suggestFix(light, "light", blocking[0])
    expect(fix).toMatch(/^#[0-9A-F]{6}$/)
    const fixed = evaluateContrast({ ...light, text: fix! }, "light")
    expect(fixed.filter((r) => r.blocking)).toEqual([])
  })
})

describe("token grammar", () => {
  it.each([
    "url(https://tracker.example/x.png)",
    "#fff; background:red",
    "red}",
    "}",
    "expression(alert(1))",
    "var(--x)",
    "var(--t-bg, url(x))",
    "var(--t-nope)",
    "@import 'x'",
    "red",
    "calc(1px + 2px)",
    "#ff0000 !important",
  ])("rejects hostile colour %s", (v) => {
    expect(validTokenValue("bg", v)).toBe(false)
  })

  it("accepts safe values per type", () => {
    expect(validTokenValue("bg", "oklch(70% 0.1 150 / 0.5)")).toBe(true)
    expect(validTokenValue("panel-border", "var(--t-border-strong)")).toBe(true)
    expect(
      validTokenValue(
        "shadow",
        "0 1px 2px rgba(0,0,0,.4), 0 14px 34px -10px #000"
      )
    ).toBe(true)
    expect(validTokenValue("shadow", "0 1px 2px url(x)")).toBe(false)
    expect(validTokenValue("display-weight", "950")).toBe(false)
    expect(validTokenValue("label-case", "lowercase")).toBe(false)
  })

  it("reports every built-in as clean and a bad font as an issue", () => {
    for (const t of BUILTIN_THEMES) expect(themeIssues(t)).toEqual([])
    const bad = {
      ...BUILTIN_THEMES[0],
      fonts: { display: "Comic Sans", body: "Inter", mono: "JetBrains Mono" },
    }
    expect(themeIssues(bad).map((i) => i.path)).toEqual(["fonts.display"])
  })
})

describe("palette derivation", () => {
  it("is deterministic and valid, and passes body AA in both modes", () => {
    const a = derivePalette({ primary: "#0F6B55", accent: "#B5673A" })
    const b = derivePalette({ primary: "#0F6B55", accent: "#B5673A" })
    expect(a).toEqual(b)
    expect(derivePalette({ primary: "#3B4FD8" })).toEqual(
      derivePalette({ primary: "#3B4FD8" })
    )
    for (const seeds of [
      { primary: "#0F6B55", accent: "#B5673A" },
      { primary: "#FFE600" },
      { primary: "#3B4FD8" },
    ]) {
      const p = derivePalette(seeds)
      const theme = {
        ...BUILTIN_THEMES[0],
        light: p.light,
        dark: p.dark,
        chart: p.chart,
        score: p.score,
      }
      expect(themeIssues(theme)).toEqual([])
      for (const mode of ["light", "dark"] as const)
        expect(
          evaluateContrast(p[mode], mode).filter((r) => r.blocking)
        ).toEqual([])
    }
  })
})

describe("colour-blind simulation", () => {
  it("collapses red and green for deuteranopia but not normal vision", () => {
    const red = parseLiteral("#D03030")
    const green = parseLiteral("#30A030")
    expect(simulate(red, null)).toEqual(red)
    const tokens = {
      ...BUILTIN_THEMES[0].light,
      good: "#3A8A3A",
      danger: "#8A6A3A",
    }
    const clashes = statusClashes(tokens, 0.08)
    expect(clashes.some((c) => c.deficiency !== null)).toBe(true)
    expect(feColorMatrixValues("achromatopsia").split(" ")).toHaveLength(20)
    expect(green).toHaveLength(4)
  })
})
