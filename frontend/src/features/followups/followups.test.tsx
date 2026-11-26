import { describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { followupsMock, seedMessage } from "@/mocks/handlers/followups"
import { appliedJobId } from "@/mocks/dataset/jobs"

configure({ asyncUtilTimeout: 6000 })

const appFor = (jobId: string) =>
  applicationsMock().apps.find((a) => a.job_id === jobId)!

describe("messages on the job page", { timeout: 20_000 }, () => {
  it("cannot approve or send a draft whose checks block, and shows the question", async () => {
    const jobId = appliedJobId(3)
    const app = appFor(jobId)
    seedMessage(app.id, {
      kind: "info_reply",
      body: "Dear hiring team,\n\nMy salary expectation is high.\n\nKind regards,",
    })
    renderApp(`/jobs/${jobId}?tab=messages`)
    const card = await screen.findByRole("listitem", {
      name: "Reply with information message",
    })
    expect(within(card).getByRole("button", { name: "Approve" })).toBeDisabled()
    expect(
      within(card).getByRole("group", { name: "Questions for you" })
    ).toHaveTextContent("Pay: What are your salary expectations?")
    expect(
      within(card).queryByRole("button", { name: "Send email" })
    ).toBeNull()
  })

  it("approves a clean draft, then sends it into the queue", async () => {
    const user = userEvent.setup()
    const jobId = appliedJobId(3)
    const app = appFor(jobId)
    const m = seedMessage(app.id)
    renderApp(`/jobs/${jobId}?tab=messages`)
    const card = await screen.findByRole("listitem", {
      name: "Follow-up message",
    })
    await user.click(within(card).getByRole("button", { name: "Approve" }))
    const send = await within(
      await screen.findByRole("listitem", { name: "Follow-up message" })
    ).findByRole("button", { name: "Send email" })
    await user.click(send)
    await waitFor(() =>
      expect(
        followupsMock().messages.find((x) => x.id === m.id)?.send_state
      ).toBe("queued")
    )
  })
})

describe("follow-ups due list", { timeout: 20_000 }, () => {
  it("marks one not needed and drafts another", async () => {
    const user = userEvent.setup()
    renderApp("/follow-ups")
    const list = await screen.findByRole("list", { name: "Follow-ups" })
    const rows = within(list).getAllByRole("listitem")
    expect(rows.length).toBeGreaterThan(0)
    const first = rows[0]
    await user.click(within(first).getByRole("button", { name: "Draft" }))
    await waitFor(() => expect(followupsMock().messages).toHaveLength(1))
  })
})

describe("wind-down", { timeout: 20_000 }, () => {
  it("pauses first, then records keep / pause / withdraw choices, and reopens", async () => {
    const user = userEvent.setup()
    renderApp("/wind-down")
    await user.click(
      await screen.findByRole("button", { name: "I've accepted an offer" })
    )
    expect(
      await screen.findByText("Automatic sending paused")
    ).toBeInTheDocument()
    const campaigns = await screen.findByRole("region", {
      name: "Campaigns and schedules",
    })
    const row = within(campaigns).getByRole("listitem", {
      name: "Analytics roles",
    })
    expect(within(row).queryByRole("button", { name: "Withdraw" })).toBeNull()
    await user.click(within(row).getByRole("button", { name: "Pause" }))
    await waitFor(() =>
      expect(
        within(row).getByRole("button", { name: "Pause" })
      ).toHaveAttribute("aria-pressed", "true")
    )
    const live = screen
      .getAllByRole("region")
      .find((r) =>
        r.getAttribute("aria-label")?.startsWith("Live applications")
      )!
    const item = within(live).getAllByRole("listitem")[0]
    await user.click(within(item).getByRole("button", { name: "Withdraw" }))
    expect(
      await within(item).findByText(/drafted for your approval/)
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Reopen my search" }))
    expect(
      await screen.findByText(/everything came back paused/)
    ).toBeInTheDocument()
  })
})
