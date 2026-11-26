import { beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { resetSourcesMock, store } from "@/mocks/data/sources"
import { renderApp } from "@/test/render"

beforeEach(() => resetSourcesMock())

describe("Run history", () => {
  it("lists runs with status, funnel and cost", async () => {
    renderApp("/autopilot/runs")
    const list = await screen.findByRole("list", { name: "Runs" })
    const cards = within(list)
      .getAllByRole("listitem", {})
      .filter((li) => li.tagName === "LI" && li.closest("ol") === list)
    expect(cards.length).toBe(5)
    expect(
      within(list).getAllByText("Done with problems").length
    ).toBeGreaterThan(0)
    expect(within(list).getAllByText("Dry run").length).toBeGreaterThan(0)
    expect(within(list).getAllByLabelText(/funnel/i).length).toBeGreaterThan(0)
  })

  it("starts a dry run from the header and shows it as running", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot/runs")
    await screen.findByRole("list", { name: "Runs" })
    await user.click(screen.getByRole("button", { name: "Dry run" }))
    await waitFor(() => expect(store.runs.length).toBe(6))
    expect(store.runs[0].dry_run).toBe(true)
  })

  it("shows a clear 'nothing was changed' banner and proposed actions on a dry run", async () => {
    renderApp("/autopilot/runs/run-4")
    expect(
      await screen.findByText("Dry run: nothing was changed")
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Senior Actuarial Analyst at Kafue Reinsurance/)
    ).toBeInTheDocument()
  })

  it("shows per-source results and errors in plain words", async () => {
    renderApp("/autopilot/runs/run-1")
    expect(
      await screen.findByRole("heading", { name: "Results by source" })
    ).toBeInTheDocument()
    expect(
      screen.queryByText("Dry run: nothing was changed")
    ).not.toBeInTheDocument()
    expect(await screen.findByText(/refused access/i)).toBeInTheDocument()
  })

  it("follows a running run and can cancel it", async () => {
    const user = userEvent.setup()
    store.runs = [
      {
        ...store.runs[0],
        id: "run-live",
        status: "running",
        counts: {},
        source_results: [],
        finished_at: null,
        started_at: new Date().toISOString(),
      },
      ...store.runs,
    ]
    store.live.set("run-live", Date.now())
    renderApp("/autopilot/runs/run-live")
    expect(await screen.findByText(/Running now/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Cancel run" }))
    await waitFor(() =>
      expect(store.runs.find((r) => r.id === "run-live")?.status).toBe(
        "cancelled"
      )
    )
  })
})
