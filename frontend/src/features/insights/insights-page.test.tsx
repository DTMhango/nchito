import { beforeEach, describe, expect, it } from "vitest"
import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { insightsMock } from "@/mocks/handlers/insights"
import { toCsv } from "./lib"

beforeEach(() => insightsMock.reset())

const section = async (name: string) =>
  (await screen.findByRole("heading", { level: 2, name })).closest("section")!

describe("Insights", () => {
  it("shows the funnel and states each small-sample rate with its caveat", async () => {
    renderApp("/insights")
    const funnel = await section("Funnel by campaign")
    expect(within(funnel).getByText("Analytics roles")).toBeInTheDocument()
    expect(
      within(funnel).getByText("Scored above threshold")
    ).toBeInTheDocument()

    const rates = await section("Reply rate")
    // 1 of 2 is never shown as 50% on its own: the count and the caveat are.
    expect(
      within(rates).getAllByText("Too few to tell").length
    ).toBeGreaterThan(0)
    expect(within(rates).getAllByText("1 of 2").length).toBeGreaterThan(0)
    expect(within(rates).queryByText("50%")).toBeNull()
    expect(within(rates).getByText("42%")).toBeInTheDocument() // 5 of 12 clears the threshold of 10
  })

  it("links every number to the filtered list with the page filters", async () => {
    const { router } = renderApp(
      "/insights?country=Zambia&since=2026-11-01&until=2026-11-30"
    )
    const funnel = await section("Funnel by campaign")
    await userEvent.click(within(funnel).getByRole("link", { name: "12" }))
    const search = router.state.location.search as Record<string, string>
    expect(router.state.location.pathname).toBe("/applications")
    expect(search).toMatchObject({
      country: "Zambia",
      since: "2026-11-01",
      until: "2026-11-30",
      campaign_id: "camp-analytics",
      reached: "sent",
    })
  })

  it("keeps the filters in the URL", async () => {
    const { router } = renderApp("/insights")
    const form = await screen.findByRole("form", { name: "Insights filters" })
    await screen.findByRole("heading", { level: 2, name: "Reply rate" })
    await userEvent.selectOptions(
      within(form).getByLabelText("Channel"),
      "email"
    )
    expect(router.state.location.search).toMatchObject({ channel: "email" })
    await userEvent.click(
      await screen.findByRole("button", { name: /clear filters/i })
    )
    expect(router.state.location.search).not.toHaveProperty("channel")
  })

  it("offers a CSV export for each table and builds valid CSV", async () => {
    renderApp("/insights")
    await section("Funnel by campaign")
    expect(
      screen.getByRole("button", { name: "Export funnel as CSV" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Export response by source as CSV" })
    ).toBeInTheDocument()
    expect(
      toCsv(
        ["a", "b"],
        [
          ["x, y", 'say "hi"'],
          [null, 2],
        ]
      )
    ).toBe('a,b\r\n"x, y","say ""hi"""\r\n,2')
  })

  it("says plainly when there is not enough data yet", async () => {
    insightsMock.setEmpty()
    renderApp("/insights")
    expect(
      await screen.findByText("There isn't enough data yet")
    ).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Reply rate" })).toBeNull()
  })
})
