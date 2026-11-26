import { beforeEach, describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { matchesMock } from "@/mocks/handlers/matches"
import { applicationsMock } from "@/mocks/handlers/applications"
import { heldSentence } from "./conflict-status"
import { appliedJobId } from "@/mocks/dataset/jobs"

// The whole app mounts per test; give a busy machine room.
configure({ asyncUtilTimeout: 6000 })

// The shared mock dataset: Copperline Bank's Head of Data (88) outranks its Senior Data
// Analyst (74), one role per employer.
const jobs = () => matchesMock.get().jobs
const winner = () =>
  jobs().find(
    (j) => j.title === "Head of Data" && j.employer === "Copperline Bank"
  )!
const held = () =>
  jobs().find(
    (j) => j.title === "Senior Data Analyst" && j.employer === "Copperline Bank"
  )!
let WIN = ""
let HELD = ""
beforeEach(() => {
  WIN = winner().id
  HELD = held().id
})

describe("job page tabs", () => {
  it("opens the tab named in the link and marks it current", async () => {
    renderApp(`/jobs/${WIN}?tab=fit`)
    expect(
      await screen.findByRole("heading", { name: "Score breakdown" })
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Fit" })).toHaveAttribute(
      "data-status",
      "active"
    )
    // the header is there whatever the tab
    expect(
      screen.getByRole("heading", { name: "Head of Data" })
    ).toBeInTheDocument()
  })

  it("falls back to Overview for an unknown tab", async () => {
    renderApp(`/jobs/${WIN}?tab=nonsense`)
    expect(await screen.findByText("At a glance")).toBeInTheDocument()
  })

  it("shows what a later-wave tab will hold", async () => {
    renderApp(`/jobs/${WIN}?tab=interview`)
    expect(await screen.findByText(/Arrives in wave 3/)).toBeInTheDocument()
  })

  it("shows the sentence behind a facet on focus", async () => {
    const user = userEvent.setup()
    const hybrid = jobs().find((j) => j.facets.work_model?.value === "hybrid")!
    renderApp(`/jobs/${hybrid.id}?tab=overview`)
    const trigger = await screen.findByRole("button", {
      name: /Work model: Hybrid/,
    })
    await user.tab() // move focus into the page, then focus the trigger directly
    trigger.focus()
    expect(
      await screen.findByText(/Three days a week in the office, two from home/)
    ).toBeInTheDocument()
  })
})

describe("held role", () => {
  it("states who outranked it and by how much", async () => {
    renderApp(`/jobs/${HELD}?tab=overview`)
    expect(
      await screen.findByText("held: outranked by Head of Data, 88 vs 74")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /Open Head of Data/ })
    ).toHaveAttribute("href", expect.stringContaining(`/jobs/${WIN}`))
  })

  it("shows the winner as a winner", async () => {
    renderApp(`/jobs/${WIN}?tab=overview`)
    expect(await screen.findByText("Winner")).toBeInTheDocument()
  })

  it("releases only with a reason", async () => {
    const user = userEvent.setup()
    renderApp(`/jobs/${HELD}?tab=overview`)
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

describe("application address", { timeout: 20_000 }, () => {
  const emailJob = () =>
    jobs().find((j) => j.apply_email && !j.application_id && !j.conflict)!

  it("shows the address, the sentence it came from and each way to apply, and confirms it", async () => {
    const user = userEvent.setup()
    const job = emailJob()
    const address = job.apply_email!.address
    renderApp(`/jobs/${job.id}?tab=overview`)
    const group = await screen.findByRole("group", {
      name: "Application address",
    })
    expect(within(group).getByTestId("apply-address")).toHaveTextContent(
      address
    )
    expect(within(group).getByTestId("address-standing")).toHaveTextContent(
      "Not confirmed"
    )
    expect(group).toHaveTextContent(
      `Send your CV and a cover letter to ${address}`
    )
    const ways = screen.getByRole("list", { name: "Ways to apply" })
    const email = within(ways).getByText("Email").closest("li")!
    expect(email).toHaveAttribute("data-available", "false")
    expect(email).toHaveTextContent("is not confirmed yet")

    await user.click(
      screen.getByRole("button", { name: "Confirm this address" })
    )
    await waitFor(() =>
      expect(screen.getByTestId("address-standing")).toHaveTextContent(
        /Confirmed by you/
      )
    )
    expect(
      within(screen.getByRole("list", { name: "Ways to apply" }))
        .getByText("Email")
        .closest("li")
    ).toHaveAttribute("data-available", "true")
    expect(job.apply_email?.usable).toBe(true)
  })

  it("corrects the address, explains a bad one by its code, and goes back to the posting's", async () => {
    const user = userEvent.setup()
    const job = emailJob()
    const posting = job.apply_email!.address
    renderApp(`/jobs/${job.id}?tab=overview`)
    await user.click(await screen.findByRole("button", { name: "Correct it" }))
    const form = screen.getByRole("form", { name: "Correct the address" })
    const box = within(form).getByLabelText("Email address")
    await user.clear(box)
    await user.type(box, "not an address")
    await user.click(
      within(form).getByRole("button", { name: "Save and confirm" })
    )
    expect(
      await screen.findByText(/That is not an email address/)
    ).toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "hiring@hr.example.com")
    await user.click(
      within(form).getByRole("button", { name: "Save and confirm" })
    )
    await waitFor(() =>
      expect(screen.getByTestId("apply-address")).toHaveTextContent(
        "hiring@hr.example.com"
      )
    )
    expect(screen.getByText(/^Set by you/)).toBeInTheDocument()
    expect(screen.getByTestId("address-standing")).toHaveTextContent(
      /Confirmed by you/
    )

    await user.click(
      screen.getByRole("button", { name: "Use the posting's address" })
    )
    await waitFor(() =>
      expect(screen.getByTestId("apply-address")).toHaveTextContent(posting)
    )
    expect(screen.getByTestId("address-standing")).toHaveTextContent(
      "Not confirmed"
    )
  })

  it("says so when the posting gives no address", async () => {
    const job = jobs().find(
      (j) => !j.apply_email && !j.application_id && !j.conflict
    )!
    renderApp(`/jobs/${job.id}?tab=overview`)
    expect(
      await screen.findByText("The posting gives no application address.")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Add an address" })
    ).toBeInTheDocument()
  })
})

describe("application tab", { timeout: 20_000 }, () => {
  it("shows a send held for quiet hours from the dispatch itself", async () => {
    const app = applicationsMock().apps.find(
      (a) => a.employer === "Nyika Labs"
    )!
    renderApp(`/jobs/${app.job_id}?tab=application`)
    const sends = await screen.findByRole("region", { name: "Sends" })
    const held = await within(sends).findByText(/Held for quiet hours until /)
    expect(held.closest("li")).toHaveAttribute("data-kind", "postponed")
  })
})

describe("messages tab", () => {
  it("lists the application's mail threads with their classification, as plain text", async () => {
    renderApp(`/jobs/${appliedJobId(3)}?tab=messages`)
    const list = await screen.findByRole("list", { name: "Threads" })
    const rows = within(list).getAllByRole("listitem")
    expect(rows.map((r) => r.dataset.classification)).toEqual([
      "information_request",
      "confirmation",
    ])
    expect(
      within(rows[0]).getByText("They ask for information")
    ).toBeInTheDocument()
    expect(rows[0]).toHaveTextContent("From talent@luangwa-re.example.com")
    expect(within(rows[0]).getByText("Check the link")).toBeInTheDocument()
    // markup in a subject is shown as text, never rendered
    expect(
      within(rows[1]).getByText(
        "We received your application <b>LR-2026-114</b>"
      )
    ).toBeInTheDocument()
    expect(rows[1].querySelector("b b")).toBeNull()
    expect(
      screen.getByText(/proposes the change, and the proposal waits for you/)
    ).toBeInTheDocument()
  })
})
