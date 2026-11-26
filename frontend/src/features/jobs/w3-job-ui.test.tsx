import { describe, expect, it } from "vitest"
import { configure, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { matchesMock } from "@/mocks/handlers/matches"
import { w3JobUiMock } from "@/mocks/handlers/w3-job-ui"
import { appliedJobId } from "@/mocks/dataset/jobs"
import { parseIds } from "./compare/api"

configure({ asyncUtilTimeout: 8000 })

const interviewJobId = () =>
  applicationsMock().apps.find((a) => a.stage === "interview")!.job_id

describe("interview pack", () => {
  it("never shows a number for unknown pay or logistics", async () => {
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    const sec = await screen.findByRole("region", { name: "Pay and logistics" })
    for (const label of [
      "Pay you told them",
      "Your pay floor",
      "Notice period",
    ]) {
      const row = within(sec).getByText(label).closest("li")!
      expect(row).toHaveAttribute("data-state", "unknown")
      expect(within(row).getByText("Decide before the interview")).toBeVisible()
      expect(row.textContent).not.toMatch(/\d/)
    }
  })

  it("flags a claim about you that no fact backs, and shows the fact chips of the others", async () => {
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    const sec = await screen.findByRole("region", { name: "Why you" })
    const bad = sec.querySelector('[data-pack-item="wy3"]')!
    expect(bad).toHaveAttribute("data-trace", "flagged")
    expect(within(bad as HTMLElement).getByText(/Untraced/)).toBeVisible()
    const good = sec.querySelector('[data-pack-item="wy1"]') as HTMLElement
    expect(good).toHaveAttribute("data-trace", "ok")
    expect(
      await within(good).findByRole("button", { name: /F-101/ })
    ).toBeVisible()
  })

  it("says which packet and CV the pack is built from", async () => {
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    expect(await screen.findByText(/Packet 2, approved/)).toBeVisible()
    expect(screen.getByText("CV v3")).toBeVisible()
  })

  it("shows the cost estimate before generating, then stops when the budget is used up", async () => {
    const user = userEvent.setup()
    w3JobUiMock.budgetExhausted = true
    renderApp(`/jobs/${appliedJobId(1)}?tab=interview`)
    expect(
      await screen.findByText(/Estimated cost: about \$0\.18/)
    ).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Generate the pack" }))
    const alert = (
      await screen.findByText("Paused: the AI budget is used up")
    ).closest("[role=alert]") as HTMLElement
    expect(
      within(alert).getByRole("link", { name: /Settings, AI/ })
    ).toHaveAttribute("href", "/settings/ai")
    expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled()
  })
})

describe("posting changes", () => {
  it("shows a failed check as unknown, never as closed", async () => {
    renderApp(`/jobs/${appliedJobId(2)}?tab=changes`)
    const row = (await screen.findByText("Couldn't check")).closest("li")!
    expect(row).toHaveTextContent(/unknown/i)
    expect(row).toHaveTextContent(/not been marked closed/)
    expect(screen.queryByText("Closed")).not.toBeInTheDocument()
  })

  it("shows before and after, and the stale-packet banner links to the Studio", async () => {
    renderApp(`/jobs/${appliedJobId(1)}?tab=changes`)
    const pay = (await screen.findByText("Pay changed")).closest("li")!
    expect(within(pay).getByText(/480,000/)).toBeVisible()
    expect(within(pay).getByText(/520,000/)).toBeVisible()
    const banner = await screen.findByRole("alert")
    expect(banner).toHaveTextContent(/posting changed after you approved/)
    expect(
      within(banner).getByRole("link", { name: /Studio/ })
    ).toHaveAttribute("href", expect.stringContaining("/studio"))
  })
})

describe("compare roles", () => {
  it("parses and limits the ids in the link", () => {
    expect(parseIds("a,b,a,c,d,e,f")).toEqual(["a", "b", "c", "d"])
  })

  it("keeps not stated apart from no", async () => {
    const jobs = matchesMock.get().jobs
    const no = jobs.find((j) => j.facets.visa_sponsorship.value === "no")!
    const unk = jobs.find(
      (j) => j.facets.visa_sponsorship.value === "not_stated"
    )!
    renderApp(`/compare?ids=${no.id},${unk.id}`)
    const row = (await screen.findByText("Visa sponsorship")).closest("tr")!
    expect(row).toHaveAttribute("data-differs", "true")
    expect(within(row).getByText("No")).toBeVisible()
    expect(within(row).getByText("Not stated")).toBeVisible()
  })

  it("shows unstated pay as not stated, never a figure", async () => {
    const jobs = matchesMock.get().jobs
    const none = jobs.find((j) => j.pay.state === "not_stated")!
    const other = jobs.find((j) => j.id !== none.id)!
    renderApp(`/compare?ids=${none.id},${other.id}`)
    await screen.findByRole("rowheader", { name: /^Pay floor/ })
    const row = document.querySelector('tr[data-row="pay"]') as HTMLElement
    expect(within(row).getAllByRole("cell")[0].textContent).not.toMatch(/\d/)
  })

  it("asks for at least two roles", async () => {
    renderApp(`/compare?ids=${appliedJobId(1)}`)
    expect(await screen.findByText("Pick at least two roles")).toBeVisible()
  })
})
