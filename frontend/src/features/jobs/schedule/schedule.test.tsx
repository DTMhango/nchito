import { describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import { renderApp, setupUser } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { calendarMock } from "@/mocks/handlers/calendar"

configure({ asyncUtilTimeout: 8000 })

const jobOf = (eventId: string) =>
  calendarMock.events().find((e) => e.id === eventId)!.job_id
const confirmed = () =>
  calendarMock
    .events()
    .find((e) => e.status === "confirmed" && e.round_number === 2)!
const proposal = () => calendarMock.events().find((e) => e.source === "mail")!

describe("Schedule tab", () => {
  it("shows both time zones with their names", async () => {
    const e = confirmed()
    renderApp(`/jobs/${e.job_id}?tab=schedule`)
    const card = await screen.findByRole("article", {
      name: "Round 2, Video call",
    })
    expect(within(card).getByText("Their time")).toBeVisible()
    expect(within(card).getByText("(Europe/London)")).toBeVisible()
    expect(within(card).getByText("Your time")).toBeVisible()
    expect(within(card).getByText("(Africa/Lusaka)")).toBeVisible()
    expect(card.textContent).toContain(e.starts_local!.slice(11, 16))
    expect(card.textContent).toContain(e.owner_starts_local!.slice(11, 16))
  })

  it("warns about an overlap and links to the interview pack", async () => {
    const e = confirmed()
    expect(e.conflicts.length).toBeGreaterThan(0)
    renderApp(`/jobs/${e.job_id}?tab=schedule`)
    const card = await screen.findByRole("article", {
      name: "Round 2, Video call",
    })
    expect(within(card).getByText(/Overlaps with/)).toBeVisible()
    const pack = within(card).getByRole("link", { name: "Interview pack" })
    expect(pack.getAttribute("href")).toContain("tab=interview")
  })

  it("labels a proposal as not confirmed and does not confirm on render", async () => {
    const p = proposal()
    renderApp(`/jobs/${p.job_id}?tab=schedule`)
    const card = await screen.findByRole("article", { name: /Round 1/ })
    expect(
      within(card).getByText(/Proposed from an email, not confirmed/)
    ).toBeVisible()
    expect(within(card).getByRole("button", { name: "Confirm" })).toBeDisabled()
    // Give any stray request time to land: nothing was posted.
    await new Promise((r) => setTimeout(r, 100))
    expect(proposal().status).toBe("proposed")
  })

  it("needs a candidate, and a time zone when the candidate has none, before it confirms", async () => {
    const user = setupUser()
    const p = proposal()
    renderApp(`/jobs/${p.job_id}?tab=schedule`)
    const card = await screen.findByRole("article", { name: /Round 1/ })
    const confirm = within(card).getByRole("button", { name: "Confirm" })
    const [optA, optB] = within(card).getAllByRole("radio")

    // Option A names no zone: the owner must give one.
    await user.click(optA)
    expect(confirm).toBeDisabled()
    await user.type(
      within(card).getByLabelText(/Which zone is that time in/),
      "Not/AZone"
    )
    expect(confirm).toBeDisabled()
    await user.clear(within(card).getByLabelText(/Which zone is that time in/))
    await user.type(
      within(card).getByLabelText(/Which zone is that time in/),
      "Africa/Nairobi"
    )
    expect(confirm).toBeEnabled()

    // Option B carries its own zone: no zone field, ready at once.
    await user.click(optB)
    expect(
      within(card).queryByLabelText(/Which zone is that time in/)
    ).toBeNull()
    expect(confirm).toBeEnabled()
    expect(proposal().status).toBe("proposed")

    await user.click(confirm)
    await waitFor(() => expect(proposal().status).toBe("confirmed"))
    expect(proposal().timezone).toBe("Africa/Nairobi")
    expect(proposal().candidates).toEqual([])
  })

  it("adds an interview in a named zone and shows both zones", async () => {
    const user = setupUser()
    const app = applicationsMock().apps.find(
      (a) => !calendarMock.events().some((e) => e.application_id === a.id)
    )!
    renderApp(`/jobs/${app.job_id}?tab=schedule`)
    await user.click(
      await screen.findByRole("button", { name: "Add interview" })
    )
    const form = await screen.findByRole("form", { name: "Add interview" })
    await user.type(
      within(form).getByLabelText(/Starts \(their wall time\)/),
      "2027-02-02T09:00"
    )
    const zone = within(form).getByLabelText(/Time zone of those times/)
    await user.clear(zone)
    await user.type(zone, "America/New_York")
    await user.click(
      within(form).getByRole("button", { name: "Save interview" })
    )
    const card = await screen.findByRole("article", {
      name: "Round 1, Video call",
    })
    expect(within(card).getByText("(America/New_York)")).toBeVisible()
    expect(within(card).getByText("(Africa/Lusaka)")).toBeVisible()
    expect(jobOf(calendarMock.events().at(-1)!.id)).toBe(app.job_id)
  })

  it("records how it went", async () => {
    const user = setupUser()
    const e = confirmed()
    renderApp(`/jobs/${e.job_id}?tab=schedule`)
    await user.click(
      await screen.findByRole("button", { name: "How did it go?" })
    )
    const form = await screen.findByRole("form", { name: "How did it go" })
    await user.selectOptions(within(form).getByLabelText("Outcome"), "mixed")
    await user.click(within(form).getByRole("button", { name: "Save" }))
    await waitFor(() =>
      expect(calendarMock.events().find((x) => x.id === e.id)!.outcome).toBe(
        "mixed"
      )
    )
  })
})
