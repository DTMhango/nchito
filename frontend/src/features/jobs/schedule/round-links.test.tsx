import { describe, expect, it } from "vitest"
import { configure, screen, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { renderApp } from "@/test/render"
import { server } from "@/test/server"
import { calendarMock } from "@/mocks/handlers/calendar"
import type { components } from "@/lib/api/types"

configure({ asyncUtilTimeout: 8000 })

type Round = components["schemas"]["InterviewRoundOut"]

const roundTwo = () =>
  calendarMock
    .events()
    .find((e) => e.status === "confirmed" && e.round_number === 2)!

function serveRounds() {
  const now = new Date().toISOString()
  const round = (n: number): Round => ({
    id: `round-${n}`,
    created_at: now,
    updated_at: now,
    round_number: n,
    scheduled_at: null,
    format: null,
    interviewers: [],
    checklist: [],
    notes: null,
    learnt: null,
    kind: n === 2 ? "technical" : "screen",
    focus: [],
    pack_id: "pack-1",
    thank_you_draft: null,
  })
  server.use(
    http.get("*/api/jobs/:jobId/interview-pack/rounds", () =>
      HttpResponse.json<Round[]>([round(1), round(2)])
    )
  )
}

describe("rounds and schedule events", () => {
  it("the pack lists the scheduled rounds, linking to the schedule", async () => {
    const e = roundTwo()
    renderApp(`/jobs/${e.job_id}?tab=interview`)
    const nav = await screen.findByRole("navigation", {
      name: "Rounds on your schedule",
    })
    const link = within(nav).getByRole("link", { name: /Round 2, video/ })
    expect(link.getAttribute("href")).toContain("tab=schedule")
  })

  it("an event's 'Prepare round' opens the mock interview on that round, which links back", async () => {
    serveRounds()
    const e = roundTwo()
    renderApp(`/jobs/${e.job_id}?tab=interview&round=2`)
    const panel = await screen.findByRole("region", { name: "Mock interview" })
    const select = await within(panel).findByRole("combobox", {
      name: "Round",
    })
    expect(select).toHaveValue("round-2")
    expect(
      await within(panel).findByText(/Round 2 is on your schedule/)
    ).toBeVisible()
    expect(
      within(panel)
        .getByRole("link", { name: "Open the schedule" })
        .getAttribute("href")
    ).toContain("tab=schedule")
  })
})
