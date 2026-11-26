import { beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { matchesMock, resetMatchesMock } from "@/mocks/handlers/matches"
import { campaignsMock } from "@/mocks/handlers/campaigns"

beforeEach(() => resetMatchesMock())

const jobList = () => screen.getByRole("list", { name: "Jobs" })
const rowTitles = () =>
  within(jobList())
    .getAllByRole("button")
    .filter((b) => !b.hasAttribute("aria-expanded"))
    .map((b) => b.querySelector(".truncate")?.textContent ?? "")
const tab = (name: RegExp) => screen.getByRole("tab", { name })
const search = (router: ReturnType<typeof renderApp>["router"]) =>
  router.state.location.search as Record<string, unknown>

async function ready() {
  await screen.findByRole("heading", { level: 2, name: "Analytics Lead" })
}

describe("Matches triage", () => {
  it("shows the inbox with tab counts, rows and the first role open", async () => {
    renderApp("/matches")
    await ready()
    await waitFor(() => expect(tab(/^New/)).toHaveTextContent(/New\s*16/))
    expect(tab(/^Held/)).toHaveTextContent("4")
    // Best score first; the held marker shows on held roles in their tab.
    expect(rowTitles()[0]).toBe("Analytics Lead")
    await userEvent.click(tab(/^Held/))
    expect(
      await screen.findAllByText(/outranked by head of data, 88 vs 74/i)
    ).not.toHaveLength(0)
  })

  it("moves with J and K, and S skips the open role", async () => {
    const { router } = renderApp("/matches")
    await ready()
    const user = userEvent.setup()
    await user.keyboard("j")
    await waitFor(() => expect(search(router).job).toBeTruthy())
    await screen.findByRole("heading", { level: 2, name: "Head of Insights" })
    await user.keyboard("k")
    await screen.findByRole("heading", { level: 2, name: "Analytics Lead" })
    await user.keyboard("s")
    await screen.findByText(/Skipped Analytics Lead/)
    const skipped = matchesMock
      .get()
      .jobs.find((j) => j.title === "Analytics Lead")
    expect(skipped?.triage).toBe("skipped")
    await waitFor(() => expect(rowTitles()).not.toContain("Analytics Lead"))
    await screen.findByRole("heading", { level: 2, name: "Head of Insights" })
  })

  it("P pins, ? opens the shortcut sheet, T says tailoring arrives in wave 2", async () => {
    renderApp("/matches")
    await ready()
    const user = userEvent.setup()
    await user.keyboard("p")
    await screen.findByText(/Pinned Analytics Lead/)
    expect(
      matchesMock.get().jobs.find((j) => j.title === "Analytics Lead")?.pinned
    ).toBe(true)
    await user.keyboard("t")
    await screen.findByText(/Tailoring arrives in wave 2/)
    await user.keyboard("?")
    expect(
      await screen.findByRole("dialog", { name: "Keyboard shortcuts" })
    ).toBeInTheDocument()
  })

  it("filters genuinely: include, exclude and not stated, kept in the URL", async () => {
    const { router } = renderApp("/matches")
    await ready()
    const user = userEvent.setup()
    await user.click(
      screen.getByRole("button", { name: "Relocation required" })
    )
    const yes = await screen.findByRole("button", {
      name: /^Yes.*Relocation required: not filtering/,
    })
    await user.click(yes)
    await waitFor(() =>
      expect(search(router).f).toEqual({
        "facets.relocation_required": { i: ["yes"] },
      })
    )
    await screen.findByText("Relocation required", { selector: "p" })
    const included = matchesMock
      .get()
      .jobs.filter(
        (j) =>
          j.triage === "new" &&
          j.conflict_state !== "held" &&
          j.facets.relocation_required?.value === "yes"
      ).length
    await waitFor(() => expect(rowTitles()).toHaveLength(included))

    await user.click(screen.getByRole("button", { name: /^Yes.*included/ }))
    await waitFor(() =>
      expect(search(router).f).toEqual({
        "facets.relocation_required": { e: ["yes"] },
      })
    )
    await screen.findByText("Not relocation required", { selector: "p" })

    await user.click(
      screen.getByRole("button", { name: /^Not stated.*not filtering/ })
    )
    await waitFor(() =>
      expect(search(router).f).toEqual({
        "facets.relocation_required": { e: ["yes"], i: ["not_stated"] },
      })
    )
    await user.keyboard("{Escape}")
    await user.click(screen.getByRole("button", { name: "Clear all" }))
    await waitFor(() => expect(search(router).f).toBeUndefined())
  })

  it("restores a linked view from the URL, grouped with counts", async () => {
    renderApp(
      "/matches?tab=new&f=" +
        encodeURIComponent(
          JSON.stringify({ "facets.relocation_required": { i: ["yes"] } })
        ) +
        "&g=facets.visa_sponsorship"
    )
    const groups = await screen.findAllByRole("button", { expanded: true })
    const jobs = matchesMock
      .get()
      .jobs.filter(
        (j) =>
          j.triage === "new" &&
          j.conflict_state !== "held" &&
          j.facets.relocation_required?.value === "yes"
      )
    const expected = new Map<string, number>()
    for (const j of jobs) {
      const v = j.facets.visa_sponsorship?.value ?? "not_stated"
      expected.set(v, (expected.get(v) ?? 0) + 1)
    }
    expect(groups).toHaveLength(expected.size)
    for (const g of groups) {
      const label = g.textContent ?? ""
      const value = label.includes("Not stated")
        ? "not_stated"
        : label.includes("Yes")
          ? "yes"
          : "no"
      expect(label).toContain(String(expected.get(value)))
    }
    // Collapse the first group: its jobs leave the list.
    const before = rowTitles().length
    await userEvent.click(groups[0])
    await waitFor(() => expect(rowTitles().length).toBeLessThan(before))
  })
})

describe("Saved views", () => {
  it("saves, renames, applies and deletes a view", async () => {
    const { router } = renderApp(
      "/matches?f=" +
        encodeURIComponent(JSON.stringify({ "pay.state": { i: ["stated"] } }))
    )
    await ready()
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: "Save view" }))
    const dialog = await screen.findByRole("dialog", { name: "Save this view" })
    await user.type(within(dialog).getByLabelText("Name"), "Pay stated")
    await user.click(within(dialog).getByRole("button", { name: "Save view" }))
    await waitFor(() =>
      expect(matchesMock.get().views.map((v) => v.name)).toContain("Pay stated")
    )
    const saved = matchesMock.get().views.find((v) => v.name === "Pay stated")!
    expect(saved.body.conditions).toMatchObject({
      root: { conditions: [{ facet: "pay.state", include: ["stated"] }] },
    })
    await waitFor(() => expect(search(router).view).toBe(saved.id))

    // Rename through the rail's menu.
    const rail = screen.getByRole("navigation", { name: "Saved views" })
    await user.click(
      within(rail).getByRole("button", { name: "Actions for Pay stated" })
    )
    await user.click(await screen.findByRole("menuitem", { name: "Rename…" }))
    const rename = await screen.findByRole("dialog", { name: "Rename view" })
    const input = within(rename).getByLabelText("Name")
    await user.clear(input)
    await user.type(input, "Paid roles")
    await user.click(within(rename).getByRole("button", { name: "Rename" }))
    await waitFor(() =>
      expect(
        saved.name === "Paid roles" ||
          matchesMock.get().views.some((v) => v.name === "Paid roles")
      ).toBe(true)
    )

    // Apply a seeded view: the URL takes its filter and grouping.
    await user.click(
      within(rail).getByRole("button", {
        name: /^Relocation roles by sponsorship/,
      })
    )
    await waitFor(() =>
      expect(search(router).g).toBe("facets.visa_sponsorship")
    )
    expect(search(router).f).toEqual({
      "facets.relocation_required": { i: ["yes"] },
    })

    // Delete.
    await user.click(
      within(rail).getByRole("button", { name: "Actions for Paid roles" })
    )
    await user.click(await screen.findByRole("menuitem", { name: "Delete…" }))
    await user.click(await screen.findByRole("button", { name: "Delete view" }))
    await waitFor(() =>
      expect(matchesMock.get().views.some((v) => v.name === "Paid roles")).toBe(
        false
      )
    )
  })

  it("previews and adds a view as a campaign rule that matches the same jobs", async () => {
    renderApp("/matches")
    await ready()
    const user = userEvent.setup()
    const rail = screen.getByRole("navigation", { name: "Saved views" })
    await user.click(
      within(rail).getByRole("button", {
        name: "Actions for Relocation, sponsorship offered",
      })
    )
    await user.click(
      await screen.findByRole("menuitem", { name: "Use as campaign rule…" })
    )
    const dialog = await screen.findByRole("dialog", {
      name: /as a campaign rule/,
    })
    const view = matchesMock.get().views[0]
    const { matches } = await import("@/mocks/handlers/matches-evaluator")
    const n = matchesMock
      .get()
      .jobs.filter((j) => matches(j, view.body.conditions as never)).length
    await within(dialog).findByText(new RegExp(`affect ${n} saved job`))
    await user.click(within(dialog).getByRole("radio", { name: /Penalty/ }))
    await user.type(within(dialog).getByLabelText(/Points/), "15")
    await user.click(within(dialog).getByRole("button", { name: "Add rule" }))
    await waitFor(() => {
      const added = campaignsMock
        .get()
        .flatMap((c) => c.criteria?.rules ?? [])
        .filter((r) => r.effect === "penalty" && r.points === 15)
      expect(added).toHaveLength(1)
      expect(added[0].conditions).toEqual(view.body.conditions)
    })
  })
})

describe("Why? panel and bulk", () => {
  it("renders each rule's value, source and what would change it", async () => {
    renderApp("/matches?tab=held")
    await screen.findByRole("heading", {
      level: 2,
      name: "Senior Data Analyst",
    })
    const why = await screen.findByRole("region", { name: "Why?" })
    expect(within(why).getByText("Held")).toBeInTheDocument()
    expect(within(why).getByText("One role per employer")).toBeInTheDocument()
    expect(within(why).getByText("Same department")).toBeInTheDocument()
    expect(within(why).getAllByText(/Settings default/).length).toBeGreaterThan(
      0
    )
    expect(
      within(why).getByText(/Outranked by Head of Data, 88 vs 74/)
    ).toBeInTheDocument()
    expect(within(why).getByText(/For it to go ahead/)).toBeInTheDocument()
    expect(
      within(why).getByText(/One role per employer: The winning role closes/)
    ).toBeInTheDocument()
  })

  it("previews a bulk archive before doing it", async () => {
    renderApp("/matches")
    await ready()
    const user = userEvent.setup()
    await user.click(
      screen.getByRole("checkbox", { name: /Select Head of Insights/ })
    )
    await user.click(
      screen.getByRole("checkbox", { name: /Select Analytics Lead/ })
    )
    const bar = screen.getByRole("toolbar", { name: "Selected jobs" })
    expect(bar).toHaveTextContent("2 selected")
    await user.click(within(bar).getByRole("button", { name: "Archive" }))
    const dialog = await screen.findByRole("dialog", {
      name: "Archive these roles?",
    })
    await within(dialog).findByText("2 roles would change.")
    expect(
      matchesMock.get().jobs.find((j) => j.title === "Analytics Lead")?.triage
    ).toBe("new")
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }))
    await waitFor(() =>
      expect(
        matchesMock.get().jobs.find((j) => j.title === "Analytics Lead")?.triage
      ).toBe("archived")
    )
  })
})
