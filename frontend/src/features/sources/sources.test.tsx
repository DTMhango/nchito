import { beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { resetSourcesMock, store } from "@/mocks/handlers/sources-data"
import { renderApp } from "@/test/render"
import { plainError } from "./words"

beforeEach(() => resetSourcesMock())

describe("Sources", () => {
  it("lists the registry with health and the last problem in plain words", async () => {
    renderApp("/sources")
    expect(await screen.findByText("Greenhouse boards")).toBeInTheDocument()
    expect(screen.getAllByText("Failing").length).toBeGreaterThan(0)
    // Raw "HTTP 403 Forbidden ..." is shown translated.
    expect(screen.getAllByText(/refused access/i).length).toBeGreaterThan(0)
  })

  it("turns a source off", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(
      await screen.findByRole("switch", { name: "Use Greenhouse boards" })
    )
    await waitFor(() =>
      expect(store.sources.find((s) => s.id === "src-gh")?.enabled).toBe(false)
    )
  })

  it("saves drawer settings and shows a test result", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(
      await screen.findByRole("button", { name: /Lever boards: open settings/ })
    )
    const rpm = await screen.findByLabelText("Requests per minute")
    await user.clear(rpm)
    await user.type(rpm, "10")
    await user.click(screen.getByRole("button", { name: "Test now" }))
    expect(await screen.findByText(/found 3 sample roles/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Save settings" }))
    await waitFor(() =>
      expect(
        store.sources.find((s) => s.id === "src-lever")?.rate_limit
          ?.requests_per_minute
      ).toBe(10)
    )
  })

  it("blocks an invalid rate limit", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(
      await screen.findByRole("button", { name: /Lever boards: open settings/ })
    )
    const rpm = await screen.findByLabelText("Requests per minute")
    await user.clear(rpm)
    await user.type(rpm, "0")
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled()
  })

  it("explains a failing test in plain words", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(
      await screen.findByRole("button", {
        name: /Workday career sites: open settings/,
      })
    )
    await user.click(await screen.findByRole("button", { name: "Test now" }))
    expect(await screen.findByText("The test failed")).toBeInTheDocument()
  })
})

describe("Watched employers", () => {
  async function openAdd() {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(
      await screen.findByRole("tab", { name: "Watched employers" })
    )
    await screen.findByText("Kafue Reinsurance")
    await user.click(screen.getAllByRole("button", { name: "Add employer" })[0])
    return user
  }

  it("shows detected board type before saving, then saves", async () => {
    const user = await openAdd()
    await user.type(
      await screen.findByLabelText("Careers links"),
      "https://jobs.lever.co/acme-metals"
    )
    await user.click(screen.getByRole("button", { name: "Check link" }))
    expect(await screen.findByText("Lever detected")).toBeInTheDocument()
    expect(store.employers.some((e) => e.board_slug === "acme-metals")).toBe(
      false
    )
    await user.click(
      screen.getByRole("button", { name: "Watch this employer" })
    )
    await waitFor(() =>
      expect(store.employers.some((e) => e.board_slug === "acme-metals")).toBe(
        true
      )
    )
  })

  it("handles a bulk paste and skips unrecognised links", async () => {
    const user = await openAdd()
    await user.type(
      await screen.findByLabelText("Careers links"),
      "https://boards.greenhouse.io/alpha https://jobs.ashbyhq.com/beta https://example.com/careers"
    )
    await user.click(screen.getByRole("button", { name: "Check 3 links" }))
    const list = await screen.findByRole("list", { name: "Detected boards" })
    expect(within(list).getByText("Greenhouse detected")).toBeInTheDocument()
    expect(within(list).getByText(/will be skipped/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Watch 2 employers" }))
    await waitFor(() => expect(store.employers.length).toBe(7))
  })
})

describe("Schedules", () => {
  it("shows three upcoming times and starts a dry run", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(await screen.findByRole("tab", { name: "Schedules" }))
    expect(await screen.findByText("Every day at 07:30")).toBeInTheDocument()
    const card = screen.getByText("Morning sweep").closest("li")!
    expect(within(card).getAllByRole("listitem")).toHaveLength(3)
    const before = store.runs.length
    await user.click(within(card).getByRole("button", { name: "Dry run" }))
    await waitFor(() => expect(store.runs.length).toBe(before + 1))
    expect(store.runs[0].dry_run).toBe(true)
  })

  it("offers cron for advanced use and rejects a bad expression", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(await screen.findByRole("tab", { name: "Schedules" }))
    await user.click(
      await screen.findByRole("button", { name: "Add schedule" })
    )
    await user.type(await screen.findByLabelText("Name"), "Custom")
    await user.click(screen.getByRole("radio", { name: "Cron" }))
    const cron = screen.getByLabelText("Cron expression")
    await user.clear(cron)
    await user.type(cron, "0 7 * *")
    expect(await screen.findByRole("alert")).toHaveTextContent(/five fields/)
    expect(screen.getByRole("button", { name: "Save schedule" })).toBeDisabled()
  })

  it("changes the missed-run choice", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(await screen.findByRole("tab", { name: "Schedules" }))
    await user.click(
      await screen.findByRole("radio", { name: "Skip until the next time" })
    )
    await waitFor(() => expect(store.missedRun).toBe("skip"))
  })
})

describe("plainError", () => {
  it("translates common failures and leaves unknown text alone", () => {
    expect(plainError("HTTP 429 Too Many Requests")).toMatch(/slow down/)
    expect(plainError("something odd")).toBe("something odd")
    expect(plainError(null)).toBe("")
  })
})
