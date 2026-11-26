import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { runnersMock } from "@/mocks/handlers/runners"
import { PC_ID } from "@/mocks/dataset/runners"
import { canUnpause, runnerRows, seenText } from "./logic"

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

  it("saves per-runner limits and shows recent activity with evidence", async () => {
    const user = userEvent.setup()
    renderApp("/settings/runners")
    const card = await runnerCard("Office PC")
    const form = await within(card).findByRole("form", {
      name: "Limits for Office PC",
    })
    const tasks = within(form).getByLabelText("Tasks per day")
    await user.clear(tasks)
    await user.type(tasks, "5")
    await user.click(within(form).getByRole("button", { name: "Save limits" }))
    await waitFor(() =>
      expect(runnersMock().caps[PC_ID].max_tasks_per_day).toBe(5)
    )

    await user.click(
      within(card).getByRole("button", { name: "Show activity" })
    )
    expect(
      await within(card).findByRole("img", { name: "Confirmation page" })
    ).toBeInTheDocument()
    expect(within(card).getAllByText(/KA-2041/).length).toBeGreaterThan(0)
    expect(await within(card).findByText(/Permit granted/)).toBeInTheDocument()
    expect(within(card).getByText(/Permit denied/)).toBeInTheDocument()
    expect(
      within(card).getByText(/The posting closed on 20 Nov/)
    ).toBeInTheDocument()
    expect(within(card).getAllByText(/Blocker:/).length).toBeGreaterThan(0)
  }, 20_000)
})
