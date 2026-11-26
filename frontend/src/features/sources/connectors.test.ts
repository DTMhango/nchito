import { describe, expect, it } from "vitest"
import type { components } from "@/lib/api/types"
import {
  buildConfig,
  draftFromConfig,
  emptyDraft,
  isNotInstalled,
  isSwitchedOff,
  parseOverride,
  searchConnectionFor,
} from "./connectors"
import { plainError } from "./words"

type SettingOut = components["schemas"]["SettingOut"]
type Connection = components["schemas"]["ConnectionOut"]

const setting = (over: Partial<SettingOut>): SettingOut => ({
  key: "sources.jobspy.results_per_board",
  group: "sources",
  label: "Results per board",
  description: "",
  kind: "int",
  value: 7,
  default: 7,
  is_default: true,
  nullable: false,
  choices: null,
  minimum: 1,
  maximum: 9,
  unit: null,
  version: 1,
  updated_by: null,
  updated_at: null,
  ...over,
})

const conn = (over: Partial<Connection>): Connection => ({
  id: "c1",
  created_at: "2026-01-02T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  provider: "search_api",
  label: "Search one",
  config: { endpoint: "https://search.example.com/api", result_path: "data" },
  secrets_masked: { api_key: "********abcd" },
  scopes_granted: [],
  reads_description: null,
  health: "unknown",
  last_checked_at: null,
  enabled: true,
  ...over,
})

describe("overrides follow the registry definition", () => {
  it("checks a number against the setting's own limits", () => {
    const s = setting({})
    expect(parseOverride(s, "5")).toEqual({ ok: true, value: 5 })
    expect(parseOverride(s, "10")).toMatchObject({ ok: false })
    expect(parseOverride(s, "0")).toMatchObject({ ok: false })
    expect(parseOverride(s, "2.5")).toMatchObject({ ok: false })
  })

  it("keeps list choices to what the setting offers", () => {
    const s = setting({ kind: "list", choices: ["indeed", "google"] })
    expect(parseOverride(s, ["google"])).toEqual({
      ok: true,
      value: ["google"],
    })
    expect(parseOverride(s, ["myspace"])).toMatchObject({ ok: false })
  })

  it("needs {title} in a query template", () => {
    const s = setting({ key: "sources.search.query_template", kind: "string" })
    expect(parseOverride(s, "jobs for {role}")).toMatchObject({ ok: false })
    expect(parseOverride(s, "{title} careers")).toMatchObject({ ok: true })
  })
})

describe("buildConfig", () => {
  it("leaves a blank override out so the setting applies", () => {
    const d = emptyDraft()
    d.overrides = { results_per_board: "", verify_links: "false" }
    d.queries = "risk analyst\n\nactuary "
    const settings = [
      setting({}),
      setting({ key: "sources.jobspy.verify_links", kind: "bool" }),
    ]
    const r = buildConfig("jobspy", d, settings, [], { results_per_board: 3 })
    expect(r).toEqual({
      ok: true,
      config: { verify_links: false, queries: ["risk analyst", "actuary"] },
    })
  })

  it("needs at least one careers page and only web addresses", () => {
    const d = emptyDraft()
    expect(buildConfig("careers_page", d, [], [])).toMatchObject({ ok: false })
    d.employers = [{ url: "ftp://example.com", name: "" }]
    expect(buildConfig("careers_page", d, [], [])).toMatchObject({ ok: false })
    d.employers = [
      { url: "https://example.com/careers", name: " Example Ltd " },
      { url: "https://example.org/jobs", name: "" },
    ]
    expect(buildConfig("careers_page", d, [], [])).toEqual({
      ok: true,
      config: {
        employers: [
          { url: "https://example.com/careers", name: "Example Ltd" },
          { url: "https://example.org/jobs" },
        ],
      },
    })
  })

  it("copies the provider shape from the connection, never its key", () => {
    const r = buildConfig("web_search", emptyDraft(), [], [conn({})])
    expect(r).toEqual({
      ok: true,
      config: {
        endpoint: "https://search.example.com/api",
        result_path: "data",
      },
    })
    expect(JSON.stringify(r)).not.toContain("abcd")
  })

  it("refuses web search with no usable connection", () => {
    expect(buildConfig("web_search", emptyDraft(), [], [])).toMatchObject({
      ok: false,
    })
    const d = { ...emptyDraft(), connectionId: "c1" }
    expect(
      buildConfig("web_search", d, [], [conn({ enabled: false })])
    ).toMatchObject({ ok: false })
  })

  it("round-trips a stored config through the draft", () => {
    const stored = {
      employers: [{ url: "https://example.com/careers", name: "Example" }],
      max_postings: 12,
    }
    const d = draftFromConfig("careers_page", stored)
    expect(d.overrides.max_postings).toBe("12")
    const s = setting({ key: "sources.careers.max_postings", maximum: 500 })
    expect(buildConfig("careers_page", d, [s], [])).toEqual({
      ok: true,
      config: stored,
    })
  })
})

describe("searchConnectionFor", () => {
  const a = conn({ id: "a", created_at: "2026-02-01T00:00:00Z" })
  const b = conn({ id: "b", created_at: "2026-01-01T00:00:00Z" })
  const off = conn({
    id: "off",
    created_at: "2025-01-01T00:00:00Z",
    enabled: false,
  })

  it("falls back to the oldest enabled connection, as the server does", () => {
    expect(searchConnectionFor("", [a, off, b])?.id).toBe("b")
  })
  it("uses the chosen one only while it is on", () => {
    expect(searchConnectionFor("a", [a, b])?.id).toBe("a")
    expect(searchConnectionFor("off", [a, off])).toBeNull()
  })
})

describe("JobSpy availability messages", () => {
  const raw =
    "ValueError: JobSpy is not installed on this server (pip install 'nchito[jobspy]')"
  it("recognises not installed and switched off", () => {
    expect(isNotInstalled(raw)).toBe(true)
    expect(isNotInstalled("HTTP 403")).toBe(false)
    expect(
      isSwitchedOff(
        "SourceError: JobSpy is switched off (setting sources.jobspy.enabled)"
      )
    ).toBe(true)
  })
  it("explains them in plain words", () => {
    expect(plainError(raw)).toMatch(/not installed on this server/)
    expect(plainError("JobSpy is switched off")).toMatch(/Discovery settings/)
    expect(
      plainError("SourceError: no API key: connect the search provider first")
    ).toMatch(/Search API connection/)
  })
})
