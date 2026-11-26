import { describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { matchesMock } from "@/mocks/handlers/matches"
import { w3JobUiMock } from "@/mocks/handlers/w3-job-ui"
import { appliedJobId } from "@/mocks/dataset/jobs"
import { parseIds } from "./compare/api"
import { valueText } from "./changes/changes-tab"

configure({ asyncUtilTimeout: 8000 })

const interviewJobId = () =>
  applicationsMock().apps.find((a) => a.stage === "interview")!.job_id

/** An applied role that is not at the interview stage (no pack yet). */
const freshJobId = () =>
  applicationsMock().apps.find((a) => a.stage !== "interview")!.job_id

describe("interview pack", () => {
  it("never shows a number where pay is undecided", async () => {
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    const sec = await screen.findByRole("region", { name: "Pay and logistics" })
    for (const topic of ["Pay you told them", "Notice period"]) {
      const row = within(sec).getByText(topic).closest("li")!
      expect(row).toHaveAttribute("data-state", "decide")
      expect(within(row).getByText(/Decide before the interview/)).toBeVisible()
      expect(row.textContent).not.toMatch(/\d/)
    }
    expect(within(sec).getByText("Not stated")).toBeVisible()
  })

  it("flags a claim no fact backs, marks the section flagged, and shows fact chips", async () => {
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    const sec = await screen.findByRole("region", { name: "Why you" })
    expect(sec).toHaveAttribute("data-flagged", "true")
    expect(within(sec).getByText(/left out of the crib sheet/)).toBeVisible()
    const bad = sec.querySelector('[data-pack-item="why_you.2"]') as HTMLElement
    expect(bad).toHaveAttribute("data-trace", "flagged")
    expect(within(bad).getByText(/Untraced/)).toBeVisible()
    const good = sec.querySelector(
      '[data-pack-item="why_you.0"]'
    ) as HTMLElement
    expect(good).toHaveAttribute("data-trace", "ok")
    expect(
      await within(good).findByRole("button", { name: /F-101/ })
    ).toBeVisible()
  })

  it("says which packet and draft the pack is built from", async () => {
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    expect(
      await screen.findByText(
        /Built from the packet you submitted \(a1b2c3d4\), draft version 3/
      )
    ).toBeVisible()
  })

  it("shows the cost estimate before generating, polls, then stops when the budget is used up", async () => {
    const user = userEvent.setup()
    w3JobUiMock.budgetExhausted = true
    renderApp(`/jobs/${freshJobId()}?tab=interview`)
    expect(
      await screen.findByText(/Estimated cost: up to \$0\.18 for 6 sections/)
    ).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Generate the pack" }))
    const alert = (
      await screen.findByText("Paused: the AI budget is used up")
    ).closest("[role=alert]") as HTMLElement
    expect(alert).toHaveTextContent(/5 sections are still to build/)
    expect(
      within(alert).getByRole("link", { name: /Settings, AI/ })
    ).toHaveAttribute("href", "/settings/ai")
    // the three sections built before the budget ran out are shown
    expect(screen.getByRole("region", { name: "Role brief" })).toBeVisible()
    await user.click(within(alert).getByRole("button", { name: "Resume" }))
    expect(
      await screen.findByRole(
        "region",
        { name: "Crib sheet" },
        { timeout: 8000 }
      )
    ).toBeVisible()
    await waitFor(() =>
      expect(
        screen.queryByText("Paused: the AI budget is used up")
      ).not.toBeInTheDocument()
    )
  })

  it("asks to reload when the stories changed elsewhere", async () => {
    const user = userEvent.setup()
    const jobId = interviewJobId()
    renderApp(`/jobs/${jobId}?tab=interview`)
    const sec = await screen.findByRole("region", { name: "Story bank" })
    await user.click(
      within(sec).getByRole("button", {
        name: "Edit story: The board KPI pack",
      })
    )
    w3JobUiMock.editStoriesElsewhere(jobId)
    await user.click(within(sec).getByRole("button", { name: "Save story" }))
    const prompt = await within(sec).findByText(/changed elsewhere/)
    await user.click(
      within(prompt.closest("[role=alert]") as HTMLElement).getByRole(
        "button",
        { name: "Reload" }
      )
    )
    expect(
      await screen.findByText("The board KPI pack (edited elsewhere)")
    ).toBeVisible()
  })

  it("saves an owner edit of a claim as a new version", async () => {
    const user = userEvent.setup()
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    const sec = await screen.findByRole("region", {
      name: "Gaps and how to address them",
    })
    await user.click(
      within(sec).getByRole("button", { name: /^Edit: Cloud data platform/ })
    )
    const box = within(sec).getByRole("textbox", {
      name: /^Edit: Cloud data platform/,
    })
    await user.clear(box)
    await user.click(box)
    await user.paste("Say plainly you have not used a cloud platform yet.")
    await user.click(within(sec).getByRole("button", { name: "Save" }))
    const region = () =>
      screen.getByRole("region", { name: "Gaps and how to address them" })
    await waitFor(() =>
      expect(region()).toHaveTextContent("Version 2, your edit")
    )
    expect(
      within(region()).getByText(/not used a cloud platform yet/)
    ).toBeVisible()
  })

  it("practises an answer: paused on budget, then retried to feedback", async () => {
    const user = userEvent.setup()
    w3JobUiMock.budgetExhausted = true
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    await user.click(
      await screen.findByRole("button", { name: "Practice mode" })
    )
    const panel = await screen.findByRole("region", { name: "Practice" })
    await user.type(within(panel).getByRole("textbox"), "I set one backlog.")
    await user.click(
      within(panel).getByRole("button", { name: "Get feedback" })
    )
    const row = await within(panel).findByText(
      "Paused: the AI budget is used up"
    )
    w3JobUiMock.budgetExhausted = false
    await user.click(
      within(row.closest("li") as HTMLElement).getByRole("button", {
        name: "Retry",
      })
    )
    expect(await within(panel).findByText(/Clear and specific/)).toBeVisible()
    expect(
      within(panel).getByText("Answer is short: add the result")
    ).toBeVisible()
  })

  it("exports and names the flagged sections", async () => {
    const user = userEvent.setup()
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    await user.click(await screen.findByRole("button", { name: "Plain text" }))
    expect(
      await screen.findByText(/Marked as failing the truth checks: Why you/)
    ).toBeVisible()
  })

  it("shows the server's auto-offer before anything is generated", async () => {
    const jobId = freshJobId()
    w3JobUiMock.offer(jobId)
    renderApp(`/jobs/${jobId}?tab=interview`)
    expect(await screen.findByText(/A pack was offered/)).toBeVisible()
    expect(
      screen.getByRole("button", { name: "Generate the pack" })
    ).toBeEnabled()
  })

  it("never mentions a thank-you draft", async () => {
    renderApp(`/jobs/${interviewJobId()}?tab=interview`)
    await screen.findByRole("region", { name: "Crib sheet" })
    expect(screen.queryByText(/thank.you/i)).not.toBeInTheDocument()
  })
})

describe("posting changes", () => {
  it("shows a failed scan as unknown, never as closed", async () => {
    renderApp(`/jobs/${appliedJobId(2)}?tab=changes`)
    const line = await screen.findByText(/whether it is still open is/)
    expect(line.closest("[data-watch]")).toHaveAttribute(
      "data-watch",
      "unknown"
    )
    expect(line.closest("[data-watch]")).toHaveTextContent(
      /not been marked closed/
    )
    expect(screen.queryByText("Closed")).not.toBeInTheDocument()
  })

  it("shows before and after, material apart from wording, and acknowledges", async () => {
    const user = userEvent.setup()
    renderApp(`/jobs/${appliedJobId(1)}?tab=changes`)
    const pay = (await screen.findByText("Pay changed")).closest(
      "li[data-change]"
    ) as HTMLElement
    expect(pay).toHaveAttribute("data-material", "true")
    expect(within(pay).getByText(/480,000/)).toBeVisible()
    expect(within(pay).getByText(/520,000/)).toBeVisible()
    const wording = document.querySelector(
      'li[data-change="c-word"]'
    ) as HTMLElement
    expect(within(wording).getByText("Wording only")).toBeVisible()

    const banner = await screen.findByText(/posting changed after you approved/)
    expect(
      within(banner.closest("[data-banner]") as HTMLElement).getByRole("link", {
        name: /Studio/,
      })
    ).toHaveAttribute("href", expect.stringContaining("/studio"))

    await user.click(within(pay).getByRole("button", { name: "Mark as seen" }))
    expect(await within(pay).findByText(/^Seen/)).toBeVisible()
    await waitFor(() =>
      expect(
        document.querySelector('[data-banner="stale-packet"]')
      ).not.toBeInTheDocument()
    )
  })

  it("writes an empty value as not stated", () => {
    expect(valueText(null)).toBe("Not stated")
    expect(valueText([])).toBe("Not stated")
    expect(valueText(["a", "b"])).toBe("a, b")
  })
})

describe("compare roles", () => {
  it("parses and limits the ids in the link", () => {
    expect(parseIds("a,b,a,c,d,e,f")).toEqual(["a", "b", "c", "d"])
  })

  it("keeps not stated apart from no", async () => {
    const jobs = matchesMock.get().jobs
    const no = jobs.find((j) => j.facets.visa_sponsorship?.value === "no")!
    const unk = jobs.find(
      (j) => (j.facets.visa_sponsorship?.value ?? "not_stated") === "not_stated"
    )!
    renderApp(`/compare?ids=${no.id},${unk.id}`)
    const row = (
      await screen.findByRole("rowheader", { name: /^Visa sponsorship/ })
    ).closest("tr")!
    expect(row).toHaveAttribute("data-differs", "true")
    expect(within(row).getByText("No")).toBeVisible()
    expect(within(row).getByText("Not stated")).toBeVisible()
  })

  it("shows unstated pay as not stated, and says why pay is not comparable", async () => {
    const jobs = matchesMock.get().jobs
    const none = jobs.find((j) => j.pay.state === "not_stated")!
    const other = jobs.find(
      (j) => j.id !== none.id && j.pay.state === "stated"
    )!
    renderApp(`/compare?ids=${none.id},${other.id}`)
    await screen.findByRole("rowheader", { name: /^Pay \(per year\)/ })
    const row = document.querySelector('tr[data-row="pay"]') as HTMLElement
    expect(row).toHaveAttribute("data-comparable", "false")
    expect(
      within(row).getByText(/Not comparable: pay is not stated for/)
    ).toBeVisible()
    const cells = within(row).getAllByRole("cell")
    expect(cells[0].textContent).not.toMatch(/\d/)
    expect(cells[0].querySelector('[data-state="not_stated"]')).not.toBeNull()
    expect(row.querySelector("[data-best]")).toBeNull()
  })

  it("names the employer group's winner", async () => {
    const jobs = matchesMock.get().jobs
    const win = jobs.find(
      (j) => j.title === "Head of Data" && j.employer === "Copperline Bank"
    )!
    const held = jobs.find(
      (j) =>
        j.title === "Senior Data Analyst" && j.employer === "Copperline Bank"
    )!
    renderApp(`/compare?ids=${win.id},${held.id}`)
    const line = await screen.findByText(/employer group's chosen role/)
    expect(line.closest("[data-winner]")).toHaveAttribute("data-winner", win.id)
  })

  it("asks for at least two roles", async () => {
    renderApp(`/compare?ids=${appliedJobId(1)}`)
    expect(await screen.findByText("Pick at least two roles")).toBeVisible()
  })
})
