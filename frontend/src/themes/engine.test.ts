import { describe, expect, it } from "vitest"
import {
  applyRoot,
  BUILTIN_THEMES,
  builtinTheme,
  DEFAULT_APPEARANCE,
  mergeThemes,
  resolveMode,
  rootState,
  themeSchema,
  themeVars,
} from "@/themes"

const copperbelt = builtinTheme("copperbelt")!

describe("built-in themes", () => {
  it("ships six valid themes with Copperbelt first", () => {
    expect(BUILTIN_THEMES.map((t) => t.id)).toEqual([
      "copperbelt",
      "midnight-ledger",
      "savanna-dusk",
      "paper",
      "workshop",
      "high-contrast",
    ])
    for (const t of BUILTIN_THEMES)
      expect(themeSchema.safeParse(t).success).toBe(true)
  })

  it("keeps the mockup's exact Copperbelt values", () => {
    expect(copperbelt.light.bg).toBe("#F2F5F3")
    expect(copperbelt.light.primary).toBe("#0F6B55")
    expect(copperbelt.dark.bg).toBe("#0C1513")
    expect(copperbelt.radius).toBe(10)
  })
})

describe("themeVars", () => {
  it("writes every token as --t-<name> for the mode", () => {
    const light = themeVars(copperbelt, "light")
    const dark = themeVars(copperbelt, "dark")
    expect(light["--t-bg"]).toBe("#F2F5F3")
    expect(dark["--t-bg"]).toBe("#0C1513")
    expect(light["--t-radius"]).toBe("10px")
    expect(light["--t-radius-sm"]).toBe("6px")
    expect(light["--t-radius-lg"]).toBe("14px")
    expect(light["--t-dens"]).toBe("11px")
    expect(light["--t-font-display"]).toContain("Bricolage Grotesque")
  })

  it("uses the mono face for figures when the theme asks for it", () => {
    const midnight = themeVars(builtinTheme("midnight-ledger")!, "dark")
    expect(midnight["--t-font-data"]).toContain("IBM Plex Mono")
    expect(themeVars(copperbelt, "light")["--t-font-data"]).toContain("Figtree")
  })

  it("applies radius, density and accent overrides", () => {
    const v = themeVars(copperbelt, "light", {
      radius: 4,
      density: "compact",
      accent_override: "cobalt",
    })
    expect(v["--t-radius"]).toBe("4px")
    expect(v["--t-dens"]).toBe("6px")
    expect(v["--t-primary"]).toBe("#1F4FD8")
    expect(v["--t-primary-soft"]).toContain("color-mix")
    const dark = themeVars(copperbelt, "dark", { accent_override: "cobalt" })
    expect(dark["--t-primary"]).toBe("#7B9BFF")
  })

  it("ignores an unknown accent", () => {
    expect(
      themeVars(copperbelt, "light", { accent_override: "not-a-colour" })[
        "--t-primary"
      ]
    ).toBe("#0F6B55")
  })
})

describe("mode and root", () => {
  it("resolves system mode from the device", () => {
    expect(resolveMode("system", true)).toBe("dark")
    expect(resolveMode("system", false)).toBe("light")
    expect(resolveMode("light", true)).toBe("light")
  })

  it("applies tokens, mode, font size and motion to <html>", () => {
    const root = document.createElement("html")
    applyRoot(
      rootState(
        copperbelt,
        {
          ...DEFAULT_APPEARANCE,
          mode: "dark",
          font_scale: 16 / 14,
          reduced_motion: true,
        },
        false
      ),
      root
    )
    expect(root.style.getPropertyValue("--t-bg")).toBe("#0C1513")
    expect(root.style.getPropertyValue("--t-font-size")).toBe("16px")
    expect(root.dataset.mode).toBe("dark")
    expect(root.dataset.themeId).toBe("copperbelt")
    expect(root.dataset.reducedMotion).toBe("true")
    expect(root.classList.contains("dark")).toBe(true)
  })

  it("removes tokens the next theme does not set", () => {
    const root = document.createElement("html")
    applyRoot(
      rootState(builtinTheme("paper")!, DEFAULT_APPEARANCE, false),
      root
    )
    expect(root.style.getPropertyValue("--t-elev-top")).toBe("2px")
    applyRoot(rootState(copperbelt, DEFAULT_APPEARANCE, false), root)
    expect(root.style.getPropertyValue("--t-elev-top")).toBe("1px")
  })
})

describe("mergeThemes", () => {
  it("adds valid custom themes and drops invalid ones", () => {
    const custom = { ...copperbelt, id: "mine", name: "Mine", builtin: false }
    const broken = { ...copperbelt, id: "broken", light: {} }
    const merged = mergeThemes([custom, broken as never])
    expect(merged.map((t) => t.id)).toContain("mine")
    expect(merged.map((t) => t.id)).not.toContain("broken")
    expect(merged).toHaveLength(BUILTIN_THEMES.length + 1)
  })
})
