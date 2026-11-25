import { beforeEach, describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { resetJobsMock } from "@/mocks/handlers/jobs"
import { heldSentence } from "./conflict-status"

// The whole app mounts per test; give a busy machine room.
configure({ asyncUtilTimeout: 6000 })

beforeEach(() => resetJobsMock())

describe("job page tabs", () => {
  it("opens the tab named in the link and marks it current", async () => {
    renderApp("/jobs/job-1?tab=fit")
    expect(
      await screen.findByRole("heading", { name: "Score breakdown" })
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Fit" })).toHaveAttribute(
      "data-status",
      "active"
    )
    // the header is there whatever the tab
    expect(
      screen.getByRole("heading", { name: "Senior Risk Analyst" })
    ).toBeInTheDocument()
  })

  it("falls back to Overview for an unknown tab", async () => {
    renderApp("/jobs/job-1?tab=nonsense")
    expect(await screen.findByText("At a glance")).toBeInTheDocument()
  })

  it("shows what a later-wave tab will hold", async () => {
    renderApp("/jobs/job-1?tab=interview")
    expect(await screen.findByText(/Arrives in wave 3/)).toBeInTheDocument()
  })

  it("shows the sentence behind a facet on focus", async () => {
    const user = userEvent.setup()
    renderApp("/jobs/job-1?tab=overview")
    const trigger = await screen.findByRole("button", {
      name: /Work model: Hybrid/,
    })
    await user.tab() // move focus into the page, then focus the trigger directly
    trigger.focus()
    expect(
      await screen.findByText(/Three days on site, two from home/)
    ).toBeInTheDocument()
  })
})

describe("held role", () => {
  it("states who outranked it and by how much", async () => {
    renderApp("/jobs/job-2?tab=overview")
    expect(
      await screen.findByText("held: outranked by Senior Risk Analyst, 88 vs 74")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /Open Senior Risk Analyst/ })
    ).toHaveAttribute("href", expect.stringContaining("/jobs/job-1"))
  })

  it("shows the winner as a winner", async () => {
    renderApp("/jobs/job-1?tab=overview")
    expect(await screen.findByText("Winner")).toBeInTheDocument()
  })

  it("releases only with a reason", async () => {
    const user = userEvent.setup()
    renderApp("/jobs/job-2?tab=overview")
    await user.click(
      await screen.findByRole("button", { name: "Release this role" })
    )
    const dialog = await screen.findByRole("dialog")
    const confirm = within(dialog).getByRole("button", { name: "Release role" })
    expect(confirm).toBeDisabled()
    await user.type(
      within(dialog).getByLabelText("Reason"),
      "Different team and manager"
    )
    expect(confirm).toBeEnabled()
    await user.click(confirm)
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(await screen.findByText("Released")).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Release this role" })
    ).toBeNull()
  })
})

describe("heldSentence", () => {
  it("falls back to the server note when the winner is unknown", () => {
    expect(heldSentence(null, null, 74, "Outranked by another role.")).toBe(
      "Outranked by another role."
    )
  })
  it("omits scores it does not have", () => {
    expect(heldSentence("Head of Risk", null, 74, null)).toBe(
      "held: outranked by Head of Risk"
    )
  })
})
