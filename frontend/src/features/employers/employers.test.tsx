import { beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import { renderApp, setupUser } from "@/test/render"
import { employersMock } from "@/mocks/handlers/bulk"
import { resetAllMocks } from "@/mocks/reset"
import {
  formFrom,
  toPolicy,
  validateOverrides,
  type OverrideForm,
} from "./overrides-editor"
import type { EmployerDetail } from "./api"

beforeEach(() => resetAllMocks())

const form = (over: Partial<OverrideForm> = {}): OverrideForm => ({
  cooldown: "",
  alwaysAsk: false,
  neverApply: false,
  neverReason: "",
  watched: false,
  priority: "0",
  notes: "",
  ...over,
})

describe("override validation", () => {
  it("accepts an empty cooldown (use the default) and rejects bad numbers", () => {
    expect(validateOverrides(form())).toEqual({})
    expect(validateOverrides(form({ cooldown: "45" }))).toEqual({})
    expect(validateOverrides(form({ cooldown: "-1" })).cooldown).toBeTruthy()
    expect(validateOverrides(form({ cooldown: "1.5" })).cooldown).toBeTruthy()
    expect(validateOverrides(form({ cooldown: "4000" })).cooldown).toMatch(
      /3650/
    )
    expect(validateOverrides(form({ priority: "101" })).priority).toBeTruthy()
    expect(validateOverrides(form({ priority: "x" })).priority).toBeTruthy()
  })

  it("never apply needs a reason; the policy carries it only when set", () => {
    expect(
      validateOverrides(form({ neverApply: true })).neverReason
    ).toBeTruthy()
    const ok = form({ neverApply: true, neverReason: " Conflict " })
    expect(validateOverrides(ok)).toEqual({})
    expect(toPolicy(ok).never_reason).toBe("Conflict")
    expect(toPolicy(form({ neverReason: "stale" })).never_reason).toBeNull()
    expect(toPolicy(form({ cooldown: "" })).cooldown_days).toBeNull()
  })

  it("starts from the employer's own values", () => {
    const d = {
      employer: {
        cooldown_days: 14,
        always_ask_first: true,
        never_apply: false,
        never_reason: null,
        watched: true,
        priority: 3,
      },
      notes: "n",
    } as unknown as EmployerDetail
    expect(formFrom(d)).toMatchObject({
      cooldown: "14",
      alwaysAsk: true,
      watched: true,
      priority: "3",
      notes: "n",
    })
  })
})

describe("Employers screens", () => {
  it("lists employers with their state, including never apply", async () => {
    renderApp("/employers")
    const table = await screen.findByRole("table", { name: "Employers" })
    const row = (
      await within(table).findByRole("link", { name: "Sahara Payments" })
    ).closest("tr")!
    expect(row).toHaveTextContent("Never apply: Conflict of interest")
    expect(
      within(
        within(table)
          .getByRole("link", { name: "Tamarind Fintech" })
          .closest("tr")!
      ).getByText("Always ask first")
    ).toBeInTheDocument()
    expect(
      within(
        within(table)
          .getByRole("link", { name: "Ndola Brewing" })
          .closest("tr")!
      ).getByText(/Cooling down until/)
    ).toBeInTheDocument()
    // The state filter narrows the list.
    const user = setupUser()
    await user.selectOptions(screen.getByLabelText("State"), "blocked")
    await waitFor(() =>
      expect(
        within(table).queryByRole("link", { name: "Tamarind Fintech" })
      ).toBeNull()
    )
    expect(
      within(table).getByRole("link", { name: "Sahara Payments" })
    ).toBeInTheDocument()
  })

  it("shows the never-apply chip on the employer's roles in Matches", async () => {
    renderApp("/matches")
    await screen.findByRole("list", { name: "Jobs" })
    const chips = await screen.findAllByText(
      "Never apply: Conflict of interest"
    )
    expect(chips.length).toBeGreaterThan(0)
    expect(chips[0]).toHaveAttribute("data-employer-state", "blocked")
  })

  it("shows the cooldown rule and ends it early only with a reason", async () => {
    renderApp("/employers/ndola%20brewing")
    await screen.findByRole("heading", { level: 2, name: "Ndola Brewing" })
    const section = await screen.findByRole("region", { name: "Cooldown" })
    expect(
      await within(section).findByText(/days after the last application ended/)
    ).toBeInTheDocument()
    const user = setupUser()
    await user.click(
      within(section).getByRole("button", { name: /End cooldown early/ })
    )
    const dialog = await screen.findByRole("dialog")
    const end = within(dialog).getByRole("button", { name: "End cooldown" })
    expect(end).toBeDisabled()
    await user.type(
      within(dialog).getByRole("textbox"),
      "Recruiter asked me to reapply"
    )
    await user.click(end)
    await waitFor(() =>
      expect(employersMock.get().endedEarly.get("ndola brewing")?.reason).toBe(
        "Recruiter asked me to reapply"
      )
    )
    await screen.findByText(/Ended early on/)
  })

  it("saves overrides, and refuses never apply without a reason", async () => {
    renderApp("/employers/mosi%20insurance")
    await screen.findByRole("heading", { level: 2, name: "Mosi Insurance" })
    const user = setupUser()
    const editor = await screen.findByRole("form", { name: "Overrides" })
    await user.click(
      within(editor).getByRole("checkbox", { name: /Never apply/ })
    )
    await user.click(
      within(editor).getByRole("button", { name: "Save overrides" })
    )
    expect(await within(editor).findByRole("alert")).toHaveTextContent(
      /Say why/
    )
    expect(
      employersMock.get().policies.get("mosi insurance")?.never_apply
    ).toBeFalsy()

    await user.type(within(editor).getByLabelText(/Why/), "Left on bad terms")
    const days = within(editor).getByLabelText(/Cooldown/)
    await user.type(days, "abc")
    await user.click(
      within(editor).getByRole("button", { name: "Save overrides" })
    )
    expect(await within(editor).findByRole("alert")).toHaveTextContent(
      /whole number/
    )
    await user.clear(days)
    await user.type(days, "14")
    await user.click(
      within(editor).getByRole("button", { name: "Save overrides" })
    )
    await waitFor(() =>
      expect(employersMock.get().policies.get("mosi insurance")).toMatchObject({
        never_apply: true,
        never_reason: "Left on bad terms",
        cooldown_days: 14,
      })
    )
    await screen.findAllByText("Never apply: Left on bad terms")
  })

  it("shows roles, the held runner-up and why", async () => {
    renderApp("/employers/copperline%20bank")
    await screen.findByRole("heading", { level: 2, name: "Copperline Bank" })
    const group = await screen.findByRole("region", {
      name: "Roles that compete",
    })
    expect(within(group).getAllByText("Held")).toHaveLength(2)
    expect(within(group).getByText("Winner")).toBeInTheDocument()
    expect(
      within(group).getAllByText(/Outranked by Head of Data/).length
    ).toBeGreaterThan(0)
  })

  it("merges into another employer and splits the name back out", async () => {
    renderApp("/employers/copperline%20insurance")
    await screen.findByRole("heading", {
      level: 2,
      name: "Copperline Insurance",
    })
    const user = setupUser()
    await user.click(screen.getByRole("button", { name: /Merge into another/ }))
    const dialog = await screen.findByRole("dialog")
    await user.type(
      within(dialog).getByPlaceholderText(/Start typing/),
      "Mosi Insurance"
    )
    await user.click(within(dialog).getByRole("button", { name: "Merge" }))
    await waitFor(() =>
      expect(employersMock.get().aliases.get("copperline insurance")).toBe(
        "Mosi Insurance"
      )
    )
    const merged = await screen.findByRole("region", { name: "Merged names" })
    await user.click(
      within(merged).getByRole("button", {
        name: /Split copperline insurance out/,
      })
    )
    await waitFor(() =>
      expect(employersMock.get().aliases.has("copperline insurance")).toBe(
        false
      )
    )
  })
})
