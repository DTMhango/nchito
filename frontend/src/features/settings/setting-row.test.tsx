import { beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithTheme } from "@/test/render"
import { resetSettingsMock } from "@/mocks/handlers/settings"
import type { SettingOut } from "./api"
import { SettingRow } from "./setting-row"
import { SettingsGroupPage } from "./settings-group-page"
import { displayValue, parseDraft, toDraft } from "./setting-value"

beforeEach(() => resetSettingsMock())

const make = (over: Partial<SettingOut>): SettingOut => ({
  key: "scoring.threshold_shortlist",
  group: "scoring",
  label: "Shortlist threshold",
  description: "Minimum score to shortlist.",
  kind: "int",
  value: 60,
  default: 60,
  is_default: true,
  nullable: false,
  choices: null,
  minimum: 0,
  maximum: 100,
  unit: "points",
  version: 0,
  updated_by: null,
  updated_at: null,
  ...over,
})

describe("parseDraft", () => {
  it.each([
    ["int", "42", 42],
    ["float", "0.9", 0.9],
    ["string", " hello ", "hello"],
    ["time", "21:00", "21:00"],
    ["cron", "0 6 * * *", "0 6 * * *"],
  ])("accepts a good %s", (kind, text, value) => {
    expect(
      parseDraft(make({ kind, minimum: null, maximum: null }), text)
    ).toEqual({ ok: true, value })
  })

  it.each([
    ["int", "4.5", "Use a whole number."],
    ["int", "abc", "Enter a number."],
    ["int", "101", "Must be at most 100."],
    ["int", "", "Enter a value."],
    ["time", "25:00", "Use a time like 21:00."],
    ["cron", "0 6 *", "Use five fields"],
  ])("rejects a bad %s (%s)", (kind, text, msg) => {
    const r = parseDraft(make({ kind }), text)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain(msg)
  })

  it("lets a nullable setting be empty", () => {
    expect(parseDraft(make({ nullable: true }), "")).toEqual({
      ok: true,
      value: null,
    })
  })

  it("keeps a choice list to its choices", () => {
    const s = make({ kind: "list", choices: ["email", "telegram"], value: [] })
    expect(parseDraft(s, ["email"])).toEqual({ ok: true, value: ["email"] })
    expect(parseDraft(s, ["sms"]).ok).toBe(false)
    expect(toDraft(s)).toEqual([])
  })

  it("reads values in plain words", () => {
    expect(displayValue(make({}), 60)).toBe("60 points")
    expect(displayValue(make({ kind: "bool", unit: null }), true)).toBe("On")
  })
})

describe("SettingRow", () => {
  it("shows a validation error and does not save", async () => {
    const user = userEvent.setup()
    renderWithTheme(<SettingRow setting={make({})} />)
    const input = screen.getByLabelText("Shortlist threshold")
    await user.clear(input)
    await user.type(input, "150")
    await user.click(
      screen.getByRole("button", { name: "Save Shortlist threshold" })
    )
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Must be at most 100."
    )
  })

  it("shows the server's message when it refuses", async () => {
    const user = userEvent.setup()
    // the mock enforces 55..100 for nothing; use a key the registry knows with a tighter max
    renderWithTheme(
      <SettingRow
        setting={make({
          key: "schedule.concurrent_sweeps",
          minimum: 0,
          maximum: 100,
          value: 1,
          default: 1,
        })}
      />
    )
    const input = screen.getByLabelText("Shortlist threshold")
    await user.clear(input)
    await user.type(input, "9")
    await user.click(
      screen.getByRole("button", { name: "Save Shortlist threshold" })
    )
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Must be at most 4."
    )
  })

  it("resets a changed setting to its default", async () => {
    const user = userEvent.setup()
    renderWithTheme(<SettingsGroupPage page="scoring" />)
    const input = await screen.findByLabelText("Shortlist threshold")
    await user.clear(input)
    await user.type(input, "70")
    await user.click(
      screen.getByRole("button", { name: "Save Shortlist threshold" })
    )
    await waitFor(() =>
      expect(screen.getByLabelText("Shortlist threshold")).toHaveValue("70")
    )
    const reset = await screen.findByRole("button", {
      name: "Reset Shortlist threshold to default",
    })
    await waitFor(() => expect(reset).toBeEnabled())
    await user.click(reset)
    await waitFor(() =>
      expect(screen.getByLabelText("Shortlist threshold")).toHaveValue("60")
    )
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Reset Shortlist threshold to default",
        })
      ).toBeDisabled()
    )
  })

  it("lists who changed it in the setting's history", async () => {
    const user = userEvent.setup()
    renderWithTheme(<SettingsGroupPage page="documents" />)
    const input = await screen.findByLabelText("CV pages")
    await user.clear(input)
    await user.type(input, "3")
    await user.click(screen.getByRole("button", { name: "Save CV pages" }))
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Reset CV pages to default" })
      ).toBeEnabled()
    )
    await user.click(screen.getByRole("button", { name: "CV pages history" }))
    const list = await screen.findByRole("list", { name: "CV pages changes" })
    expect(list).toHaveTextContent("2 pages to 3 pages")
    expect(list).toHaveTextContent("owner")
  })
})

describe("renderer by value type", () => {
  it("draws a switch, a select, checkboxes, a time and a number from metadata alone", async () => {
    const user = userEvent.setup()
    renderWithTheme(<SettingsGroupPage page="automation" />)
    expect(
      await screen.findByRole("switch", { name: "Paused" })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Default mode").tagName).toBe("SELECT")
    expect(screen.getByLabelText("Quiet hours start")).toHaveAttribute(
      "type",
      "time"
    )
    expect(screen.getByLabelText("Daily cap")).toHaveValue("5")
    await user.click(screen.getByRole("switch", { name: "Paused" }))
    await user.click(screen.getByRole("button", { name: "Save Paused" }))
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Reset Paused to default" })
      ).toBeEnabled()
    )
  })

  it("draws checkboxes for a choice list", async () => {
    renderWithTheme(<SettingsGroupPage page="notifications" />)
    const group = await screen.findByRole("group", { name: "Channels" })
    expect(group.querySelectorAll("[role=checkbox]")).toHaveLength(3)
  })
})

describe("wave 4 settings render sensibly", () => {
  it("free lists are one item per line, so an item may hold a comma", () => {
    const s = make({ kind: "list", choices: null, value: ["a, b", "c"] })
    expect(toDraft(s)).toBe("a, b\nc")
    expect(parseDraft(s, "a, b\n\n c \r\nd")).toEqual({
      ok: true,
      value: ["a, b", "c", "d"],
    })
  })

  it("shows the tailoring tool-check lists as editable lines", async () => {
    renderWithTheme(<SettingsGroupPage page="tailoring" />)
    const terms = await screen.findByLabelText("Tool and technology names")
    expect(terms.tagName).toBe("TEXTAREA")
    expect((terms as HTMLTextAreaElement).value.split("\n")).toContain("Python")
    expect(
      screen.getByLabelText("Wording that names a tool without claiming it")
        .tagName
    ).toBe("TEXTAREA")
    expect(
      screen.getByRole("switch", { name: "Catch unknown technical names" })
    ).toBeInTheDocument()
  })

  it("picks the default mailbox from connected mailboxes, not a text box", async () => {
    renderWithTheme(<SettingsGroupPage page="mail" />)
    const pick = await screen.findByLabelText("Default mailbox")
    expect(pick.tagName).toBe("SELECT")
    expect(
      screen.getByRole("option", { name: "The first mailbox connected" })
    ).toBeInTheDocument()
  })

  it.each([
    ["insights", "Insights"],
    ["themes", "Theme studio"],
    ["calendar", "Calendar"],
    ["preferences", "Preference learning"],
    ["bulk", "Bulk actions"],
    ["followups", "Follow-ups and wind-down"],
  ] as const)("has a %s page with its settings", async (page, title) => {
    renderWithTheme(<SettingsGroupPage page={page} />)
    expect(
      await screen.findByRole("heading", { name: title })
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /^Save / }).length).toBe(
        screen.getAllByRole("listitem").length
      )
    )
    expect(screen.getAllByRole("listitem").length).toBeGreaterThan(2)
  })

  it("shows the mock interview settings on the Interview page", async () => {
    renderWithTheme(<SettingsGroupPage page="interview" />)
    expect(
      await screen.findByLabelText("Mock interview rubric")
    ).toBeInTheDocument()
  })
})
