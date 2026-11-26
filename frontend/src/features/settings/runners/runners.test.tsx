import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp, setupUser } from "@/test/render"
import { runnersMock } from "@/mocks/handlers/runners"
import { ACTION, PC_ID, runnerTask } from "@/mocks/dataset/runners"
import {
  canUnpause,
  currentTaskText,
  reinstateErrorText,
  runnerRows,
  seenText,
} from "./logic"

/** A runner's card: the Tokens list has a row with the same name, so look in the Runners list. */
const runnerCard = async (name: string) => {
  const list = await screen.findByRole("list", { name: "Runners" })
  return waitFor(() => within(list).getByRole("listitem", { name }))
}

describe("token secret", () => {
  it("is shown once and cannot be found after the dialog closes", async () => {
    const user = userEvent.setup()
    renderApp("/settings/runners")
    await user.click(
      await screen.findByRole("button", { name: /create a token/i })
    )
    const dialog = await screen.findByRole("dialog")
    await user.type(within(dialog).getByLabelText("Name"), "Spare laptop")
    await user.click(
      within(dialog).getByRole("button", { name: "Create token" })
    )

    const secret = (await screen.findByTestId("token-secret")).textContent ?? ""
    expect(secret).toMatch(/^nch_live_/)
    expect(screen.getByText(/you won't see this again/i)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "I've copied it" }))
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    )
    // The new token is listed by name and start only.
    const list = await screen.findByRole("list", { name: "Tokens" })
    expect(within(list).getByText("Spare laptop")).toBeInTheDocument()
    expect(document.body.textContent).not.toContain(secret)

    // Opening the dialog again starts blank: nothing is carried over.
    await user.click(screen.getByRole("button", { name: /create a token/i }))
    expect(screen.queryByTestId("token-secret")).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain(secret)
  })

  it("never comes back from the token list", async () => {
    const res = await fetch("/api/tokens", { credentials: "include" })
    const tokens = (await res.json()) as Record<string, unknown>[]
    expect(tokens.length).toBeGreaterThan(0)
    for (const t of tokens) expect(t).not.toHaveProperty("token")
  })
})

describe("paused for a violation", () => {
  it("cannot be un-paused until the owner acknowledges the reason", async () => {
    const user = userEvent.setup()
    renderApp("/settings/runners")
    const card = await runnerCard("Old laptop")
    expect(card).toHaveAttribute("data-paused", "true")
    expect(
      within(card).getByText(/submission to a Lever form was reported/i)
    ).toBeInTheDocument()
    const button = within(card).getByRole("button", { name: "Un-pause runner" })
    expect(button).toBeDisabled()

    await user.click(button) // no effect while disabled
    expect(
      runnersMock().tokens.find((t) => t.name === "Old laptop")!.suspended_at
    ).not.toBeNull()

    await user.click(
      within(card).getByRole("checkbox", { name: /i have read why/i })
    )
    expect(button).toBeEnabled()
    await user.click(button)
    await waitFor(() =>
      expect(
        runnersMock().tokens.find((t) => t.name === "Old laptop")!.suspended_at
      ).toBeNull()
    )
  })

  it("logic: un-pause needs both a paused runner and the acknowledgement", () => {
    expect(canUnpause(false, true)).toBe(false)
    expect(canUnpause(true, false)).toBe(false)
    expect(canUnpause(true, true)).toBe(true)
  })
})

describe("stale runners", () => {
  it("highlights a runner that stopped checking in and not one that is online", async () => {
    renderApp("/settings/runners")
    const stale = await runnerCard("Home server")
    expect(stale).toHaveAttribute("data-stale", "true")
    expect(within(stale).getByText("Not responding")).toBeInTheDocument()
    expect(within(stale).getByText(/seen 2 hours ago/)).toBeInTheDocument()
    const fresh = await runnerCard("Office PC")
    expect(fresh).not.toHaveAttribute("data-stale")
    expect(within(fresh).getByText("Online")).toBeInTheDocument()
  })

  it("logic: joins tokens, marks offline runners stale and paused ones with their reason", () => {
    const m = runnersMock()
    const rows = runnerRows(m.statuses, m.tokens)
    expect(rows.find((r) => r.status.name === "Office PC")!.stale).toBe(false)
    expect(rows.find((r) => r.status.name === "Home server")!.stale).toBe(true)
    const paused = rows.find((r) => r.status.name === "Old laptop")!
    expect(paused.paused).toBe(true)
    expect(paused.pausedReason).toMatch(/without a granted permit/)
    expect(seenText(null)).toBe("never seen")
  })
})

describe("page content", () => {
  it("states what a runner can and cannot do and that the browser is instructed and audited", async () => {
    renderApp("/settings/runners")
    await screen.findByRole("heading", { name: "Runners and tokens" })
    expect(screen.getByText(/never types a password/i)).toBeInTheDocument()
    expect(screen.getByText(/instructed and audited/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Use my PC \(Claude Code \+ Chrome\)/)
    ).toBeInTheDocument()
    expect(screen.getByText(/off by default/i)).toBeInTheDocument()
    expect(screen.getAllByText(/--profile runner/).length).toBeGreaterThan(0)
  })

  it("shows the runner settings read-only per runner, with a link to edit them", async () => {
    renderApp("/settings/runners")
    const card = await runnerCard("Office PC")
    const limits = await within(card).findByRole("region", {
      name: "Limits for Office PC",
    })
    expect(within(limits).getByText("Task lease")).toBeInTheDocument()
    expect(within(limits).getByText("20 minutes")).toBeInTheDocument()
    expect(within(limits).queryByRole("textbox")).toBeNull()
    expect(
      within(limits).getByRole("link", { name: "Change in runner settings" })
    ).toHaveAttribute("href", "#runner-settings")
    // The server runner also shows its spend and token caps.
    const server = await runnerCard("Home server")
    expect(await within(server).findByText(/minor units/)).toBeInTheDocument()
    // The runners group is editable in one place, through the settings API.
    const settings = screen.getByRole("list", { name: "Runner settings" })
    expect(within(settings).getAllByRole("listitem").length).toBeGreaterThan(5)
  })

  it("shows the current task's title and type on the card", async () => {
    renderApp("/settings/runners")
    const card = await runnerCard("Office PC")
    expect(
      within(card).getByText(
        "Applying: Grid Data Analyst at Copperline Energy."
      )
    ).toBeInTheDocument()
    const idle = await runnerCard("Home server")
    expect(
      within(idle).getByText(/Not working on anything right now/)
    ).toBeInTheDocument()
    expect(
      currentTaskText({
        current_task_id: "t",
        current_task_title: "careers.example.com",
        current_task_type: "sweep_site",
      })
    ).toBe("Sweeping a site: careers.example.com.")
  })

  it("shows the runner's real tasks: checkpoint, blockers, permit decisions, result and evidence", async () => {
    const user = setupUser()
    renderApp("/settings/runners")
    const card = await runnerCard("Office PC")
    await user.click(
      within(card).getByRole("button", { name: "Show activity" })
    )
    const activity = await within(card).findByRole("region", {
      name: "Recent activity of Office PC",
    })
    const tasks = await within(activity).findByRole("list", { name: "Tasks" })
    const rows = within(tasks).getAllByRole("listitem", {
      name: /at |careers/,
    })
    expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual([
      "Grid Data Analyst at Copperline Energy",
      "Credit Analyst at Luangwa Re",
      "careers.example.com",
    ])
    const current = rows[0]
    expect(
      within(current).getByText(/filled the contact page · 3 fields filled/)
    ).toBeInTheDocument()
    expect(within(current).getByText("CAPTCHA")).toBeInTheDocument()
    expect(within(current).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      `/accounts/handoff/${ACTION.captcha}`
    )
    expect(within(current).getByText("Waiting for you")).toBeInTheDocument()
    expect(
      within(current).getByText(/cover letter changed since you approved it/)
    ).toBeInTheDocument()
    expect(
      within(current).getByText("Changed since approval: cover_letter")
    ).toBeInTheDocument()
    const done = rows[1]
    expect(within(done).getByText("Permit granted")).toBeInTheDocument()
    expect(
      within(done).getByText(
        /submitted · Confirmation page shown · reference LR-2041/
      )
    ).toBeInTheDocument()
    expect(within(done).getByText(/confirm\.png/)).toBeInTheDocument()
    expect(within(rows[2]).getByText("Sweeping a site")).toBeInTheDocument()
    // No more pages: no "older" button.
    expect(
      within(activity).queryByRole("button", { name: "Show older tasks" })
    ).toBeNull()
  })

  it("pages older tasks with the server's cursor", async () => {
    const m = runnersMock()
    m.tasks[PC_ID] = Array.from({ length: 25 }, (_, i) =>
      runnerTask(i + 1, { title: `Task number ${i + 1}` })
    )
    const user = setupUser()
    renderApp("/settings/runners")
    const card = await runnerCard("Office PC")
    await user.click(
      within(card).getByRole("button", { name: "Show activity" })
    )
    const tasks = await within(card).findByRole("list", { name: "Tasks" })
    await waitFor(() =>
      expect(within(tasks).getAllByRole("listitem")).toHaveLength(20)
    )
    await user.click(
      within(card).getByRole("button", { name: "Show older tasks" })
    )
    await waitFor(() =>
      expect(within(tasks).getAllByRole("listitem")).toHaveLength(25)
    )
    expect(within(tasks).getByText("Task number 25")).toBeInTheDocument()
    expect(
      within(card).queryByRole("button", { name: "Show older tasks" })
    ).toBeNull()
  })

  it("answers 404 for an unknown token", async () => {
    const res = await fetch(
      "/api/tokens/00000000-0000-4000-8000-000000000000/tasks",
      { credentials: "include" }
    )
    expect(res.status).toBe(404)
  })
})

describe("un-pause refusals", () => {
  it("sends acknowledged and a note; the server refuses without the acknowledgement", async () => {
    const paused = runnersMock().tokens.find((t) => t.name === "Old laptop")!
    const call = (body: unknown) =>
      fetch(`/api/tokens/${paused.id}/reinstate`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    const refused = await call({ acknowledged: false })
    expect(refused.status).toBe(422)
    expect(await refused.json()).toMatchObject({
      detail: { code: "acknowledgement_required" },
    })
    expect((await call({ acknowledged: true, note: "checked" })).status).toBe(
      200
    )
  })

  it("words a 409 for a revoked token and a 422 acknowledgement refusal", async () => {
    const { ApiError } = await import("@/lib/api/client")
    expect(reinstateErrorText(new ApiError(409, { detail: "x" }), "f")).toMatch(
      /revoked/
    )
    expect(
      reinstateErrorText(
        new ApiError(422, {
          detail: { code: "acknowledgement_required", reason: "r" },
        }),
        "f"
      )
    ).toMatch(/Tick the box/)
    expect(reinstateErrorText(new Error("x"), "fallback")).toBe("fallback")
  })
})
