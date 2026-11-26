import { beforeEach, describe, expect, it } from "vitest"
import { screen, within } from "@testing-library/react"
import { renderApp } from "@/test/render"
import { setupUser } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { bulkMock } from "@/mocks/handlers/bulk"
import { matchesMock } from "@/mocks/handlers/matches"
import { resetAllMocks } from "@/mocks/reset"

beforeEach(() => resetAllMocks())

const pick = async (
  user: ReturnType<typeof setupUser>,
  dialog: HTMLElement,
  label: string
) => {
  await user.selectOptions(within(dialog).getByLabelText("Action"), label)
}

async function openMatchesBulk(
  user: ReturnType<typeof setupUser>,
  tab: string
) {
  renderApp(`/matches?tab=${tab}`)
  await screen.findByRole("list", { name: "Jobs" })
  return user
}

const tick = (name: RegExp) => screen.findByRole("checkbox", { name })

describe("bulk dialog on Matches", () => {
  it("previews first, grouped by reason, and changes nothing until run", async () => {
    const user = setupUser()
    await openMatchesBulk(user, "held")
    await user.click(await tick(/Select Senior Data Analyst/))
    await user.click(await tick(/Select Data Manager/))
    const bar = screen.getByRole("toolbar", { name: "Selected jobs" })
    await user.click(within(bar).getByRole("button", { name: "More actions" }))
    const dialog = await screen.findByRole("dialog")
    await within(dialog).findByRole("option", { name: "Send for approval" })
    await pick(user, dialog, "Send for approval")
    await user.click(within(dialog).getByRole("button", { name: "Preview" }))
    const summary = await within(dialog).findByTestId("preview-summary")
    expect(summary).toHaveTextContent("2 selected: 0 will change, 2 can't.")
    const group = within(dialog)
      .getByText(/2 can't: Held/)
      .closest("li")!
    expect(group).toHaveAttribute("data-reason", "held")
    expect(group).toHaveTextContent(/Outranked by Head of Data/)
    // Nothing to run when nothing would change.
    expect(
      within(dialog).getByRole("button", { name: /Run on 0 items/ })
    ).toBeDisabled()
  })

  it("offers everything matching the view and confirms the server's count", async () => {
    const user = setupUser()
    await openMatchesBulk(user, "new")
    await user.click(await tick(/Select Analytics Lead/))
    const bar = screen.getByRole("toolbar", { name: "Selected jobs" })
    await user.click(within(bar).getByRole("button", { name: "Archive" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(
      within(dialog).getByRole("radio", {
        name: /Everything matching this view/,
      })
    )
    await user.click(within(dialog).getByRole("button", { name: "Preview" }))
    const summary = await within(dialog).findByTestId("preview-summary")
    const expected = matchesMock
      .get()
      .jobs.filter((j) => j.triage === "new").length
    expect(summary.textContent).toMatch(/^(\d+) selected: \1 will change/)
    expect(
      Number(/^(\d+)/.exec(summary.textContent ?? "")?.[1])
    ).toBeGreaterThan(1)
    expect(
      Number(/^(\d+)/.exec(summary.textContent ?? "")?.[1])
    ).toBeLessThanOrEqual(expected)
  })

  it("runs with live progress, lists a partial failure, and retries it", async () => {
    const user = setupUser()
    bulkMock.chunk = 1
    await openMatchesBulk(user, "new")
    const boxes = (
      await screen.findAllByRole("checkbox", { name: /^Select / })
    ).slice(0, 3)
    const jobs = boxes.map((box) => {
      const label = box.getAttribute("aria-label") ?? ""
      return matchesMock
        .get()
        .jobs.find((j) => label === `Select ${j.title}, ${j.employer}`)!
    })
    const [a, b] = jobs
    bulkMock.failIds = new Set([b.id])
    for (const box of boxes) await user.click(box)
    const bar = screen.getByRole("toolbar", { name: "Selected jobs" })
    await user.click(within(bar).getByRole("button", { name: "Tag" }))
    const dialog = await screen.findByRole("dialog")
    await user.type(within(dialog).getByLabelText("Tag"), "review")
    await user.click(within(dialog).getByRole("button", { name: "Preview" }))
    await within(dialog).findByText(/3 selected: 3 will change/)
    await user.click(
      within(dialog).getByRole("button", { name: /Run on 3 items/ })
    )
    expect(
      await within(dialog).findByRole("progressbar", { name: "Progress" })
    ).toBeInTheDocument()
    await within(dialog).findByRole(
      "heading",
      { name: /done with some failures/ },
      { timeout: 4000 }
    )
    expect(
      within(dialog).getByText("3 of 3 done", { exact: false })
    ).toBeInTheDocument()
    const failed = (await within(dialog).findByText(/Failed \(1\)/))
      .parentElement!
    expect(failed).toHaveTextContent(b.title)
    expect(failed).toHaveTextContent(/could not be reached/)
    expect(matchesMock.get().jobs.find((j) => j.id === a.id)?.tags).toContain(
      "review"
    )
    expect(
      matchesMock.get().jobs.find((j) => j.id === b.id)?.tags
    ).not.toContain("review")

    // Retry runs only the failed item.
    bulkMock.failIds = new Set()
    await user.click(
      within(dialog).getByRole("button", { name: "Retry failed items" })
    )
    await within(dialog).findByRole(
      "heading",
      { name: /Tag: done$/ },
      { timeout: 4000 }
    )
    expect(matchesMock.get().jobs.find((j) => j.id === b.id)?.tags).toContain(
      "review"
    )
  })

  it("offers undo for a reversible action and puts the change back", async () => {
    const user = setupUser()
    await openMatchesBulk(user, "new")
    const job = matchesMock
      .get()
      .jobs.find((j) => j.title === "Analytics Lead")!
    const before = job.triage
    await user.click(await tick(/Select Analytics Lead/))
    const bar = screen.getByRole("toolbar", { name: "Selected jobs" })
    await user.click(within(bar).getByRole("button", { name: "Archive" }))
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Preview" }))
    await within(dialog).findByText(/You can undo this for 15 minutes/)
    await user.click(
      within(dialog).getByRole("button", { name: /Run on 1 item/ })
    )
    const undo = await within(dialog).findByRole("button", { name: "Undo" })
    expect(job.triage).toBe("archived")
    await user.click(undo)
    await within(dialog).findByText(/Archive: undone/)
    expect(job.triage).toBe(before)
    expect(within(dialog).queryByRole("button", { name: "Undo" })).toBeNull()
  })

  it("lists approve-reviewed only when the setting allows it", async () => {
    const user = setupUser()
    await openMatchesBulk(user, "new")
    await user.click(await tick(/Select Analytics Lead/))
    const bar = screen.getByRole("toolbar", { name: "Selected jobs" })
    await user.click(within(bar).getByRole("button", { name: "More actions" }))
    const dialog = await screen.findByRole("dialog")
    await within(dialog).findByRole("option", { name: "Send for approval" })
    expect(
      within(dialog).queryByRole("option", { name: /Approve all reviewed/ })
    ).toBeNull()
    expect(
      within(dialog).queryByRole("option", { name: /approve and send/i })
    ).toBeNull()
  })
})

describe("bulk dialog on Applications", () => {
  it("shows a held runner-up as refused with the reason, and offers no undo for a send", async () => {
    const user = setupUser()
    const apps = applicationsMock().apps
    const winner = apps.find((a) => a.employer === "Luangwa Re")!
    const runnerUp = apps.find((a) => a.employer === "Copperline Energy")!
    const job = matchesMock.get().jobs.find((j) => j.id === runnerUp.job_id)!
    job.conflict_state = "held"
    job.conflict = {
      state: "held",
      note: "Outranked by Risk Lead, 90 vs 74",
    } as never

    renderApp("/applications")
    await user.click(
      await screen.findByRole("checkbox", {
        name: `Select ${winner.employer}, ${winner.title}`,
      })
    )
    await user.click(
      screen.getByRole("checkbox", {
        name: `Select ${runnerUp.employer}, ${runnerUp.title}`,
      })
    )
    const bar = screen.getByRole("toolbar", { name: "Selected applications" })
    await user.click(
      within(bar).getByRole("button", { name: "Send for approval" })
    )
    const dialog = await screen.findByRole("dialog")
    await user.click(within(dialog).getByRole("button", { name: "Preview" }))
    await within(dialog).findByText(/2 selected: 1 will change, 1 can't/)
    expect(within(dialog).getByText(/can't: Held/)).toBeInTheDocument()
    expect(
      within(dialog).getByText(/This one cannot be undone/)
    ).toBeInTheDocument()
    await user.click(
      within(dialog).getByRole("button", { name: /Run on 1 item/ })
    )
    const refused = (
      await within(dialog).findByText(/Refused \(1\)/, undefined, {
        timeout: 4000,
      })
    ).parentElement!
    expect(refused).toHaveTextContent("Risk Data Manager, Copperline Energy")
    expect(refused).toHaveTextContent(/Held: Outranked by Risk Lead/)
    expect(within(dialog).queryByRole("button", { name: "Undo" })).toBeNull()
    expect(dialog.querySelector('[data-outcome="changed"]')).toHaveTextContent(
      "1 changed"
    )
  })

  it("needs a reason to skip and a date to snooze before it will preview", async () => {
    const user = setupUser()
    renderApp("/applications")
    await user.click(
      await screen.findByRole("checkbox", {
        name: /Select Kafue Analytics, Head of Data/,
      })
    )
    const bar = screen.getByRole("toolbar", { name: "Selected applications" })
    await user.click(within(bar).getByRole("button", { name: "More actions" }))
    const dialog = await screen.findByRole("dialog")
    await within(dialog).findByRole("option", { name: "Skip" })
    await pick(user, dialog, "Skip")
    const preview = within(dialog).getByRole("button", { name: "Preview" })
    expect(preview).toBeDisabled()
    await user.type(within(dialog).getByLabelText(/Reason/), "Not a fit")
    expect(preview).toBeEnabled()
    await pick(user, dialog, "Snooze")
    expect(
      within(dialog).getByRole("button", { name: "Preview" })
    ).toBeDisabled()
  })
})
