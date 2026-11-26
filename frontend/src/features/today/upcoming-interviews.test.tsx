import { describe, expect, it } from "vitest"
import { screen, within } from "@testing-library/react"
import { renderApp } from "@/test/render"
import { calendarMock } from "@/mocks/handlers/calendar"

describe("Today: upcoming interviews", () => {
  it("shows employer, both zones, overlap badge and a link to the schedule", async () => {
    renderApp("/today")
    const block = await screen.findByRole("region", {
      name: "Upcoming interviews",
    })
    const first = calendarMock.events().find((e) => e.round_number === 2)!
    const link = await within(block).findByRole("link", {
      name: first.employer,
    })
    expect(link.getAttribute("href")).toContain("tab=schedule")
    expect(within(block).getAllByText("(Europe/London)").length).toBe(1)
    expect(
      within(block).getAllByText("(Africa/Lusaka)").length
    ).toBeGreaterThan(0)
    expect(within(block).getAllByText("Overlaps another event").length).toBe(2)
  })

  it("lists a proposal that needs a time from the owner", async () => {
    renderApp("/today")
    const block = await screen.findByRole("region", {
      name: "Upcoming interviews",
    })
    expect(
      await within(block).findByText("Needs a time from you")
    ).toBeVisible()
    expect(within(block).getByText(/2 possible times/)).toBeVisible()
  })
})
