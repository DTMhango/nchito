import { describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { renderApp } from "@/test/render"
import { server } from "@/test/server"
import { applicationsMock } from "@/mocks/handlers/applications"
import { autopilotMock } from "@/mocks/handlers/autopilot"
import { matchesMock } from "@/mocks/handlers/matches"

configure({ asyncUtilTimeout: 6000 })

const appOf = (employer: string) =>
  applicationsMock().apps.find((a) => a.employer === employer)!
const jobOf = (jobId: string) =>
  matchesMock.get().jobs.find((j) => j.id === jobId)!

describe("packet review", { timeout: 20_000 }, () => {
  it("confirms an unconfirmed address and offers to prepare the manual packet again", async () => {
    const user = userEvent.setup()
    const app = appOf("Zambezi Mining Systems")
    app.channel = "manual"
    const job = jobOf(app.job_id)
    job.apply_email = {
      address: "careers@zambezi.example.com",
      found_in: "posting_text",
      evidence: "Apply to careers@zambezi.example.com.",
      confirmed: false,
      confirmed_by: null,
      confirmed_at: null,
      trusted_domain: false,
      usable: false,
    }
    const prepared: unknown[] = []
    server.use(
      http.post(
        "*/api/applications/:id/packet/prepare",
        async ({ request }) => {
          prepared.push(await request.json())
          const packet = autopilotMock().packets[app.id]?.at(-1)
          return HttpResponse.json({
            channel: "email",
            packet,
            created: true,
            changes: [],
            approval: null,
          })
        }
      )
    )
    renderApp(`/approvals/${app.id}`)
    const notice = await screen.findByRole("group", {
      name: "Unconfirmed application address",
    })
    expect(notice).toHaveTextContent("careers@zambezi.example.com")
    expect(notice).toHaveTextContent("prepared for you to apply yourself")
    await user.click(
      within(notice).getByRole("button", { name: "Confirm the address" })
    )
    const status = await screen.findByText(/Address confirmed/)
    expect(job.apply_email?.usable).toBe(true)
    await user.click(
      within(status.closest("[role=status]") as HTMLElement).getByRole(
        "button",
        { name: "Prepare again" }
      )
    )
    await waitFor(() => expect(prepared).toEqual([{ channel: "auto" }]))
  })

  it("reads a superseded packet by its code and offers the latest version", async () => {
    const user = userEvent.setup()
    const app = appOf("Zambezi Mining Systems")
    renderApp(`/approvals/${app.id}`)
    const approve = await screen.findByRole("button", {
      name: "Let the agent submit",
    })
    const current = autopilotMock().packets[app.id].at(-1)!
    current.version = 3
    current.content_hash = "c".repeat(64)
    await user.click(approve)
    const alert = (
      await screen.findByText(/A newer version of this packet exists/)
    ).closest("[role=alert]") as HTMLElement
    expect(alert).toHaveAttribute("data-code", "packet_superseded")
    expect(alert).toHaveTextContent(/packet changed since you opened it/i)
    await user.click(
      within(alert).getByRole("button", { name: "Load the latest version" })
    )
    await waitFor(() =>
      expect(
        screen.queryByText(/A newer version of this packet exists/)
      ).not.toBeInTheDocument()
    )
  })
})
