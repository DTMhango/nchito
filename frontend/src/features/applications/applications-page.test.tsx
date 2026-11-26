import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it } from "vitest"
import { renderApp } from "@/test/render"
import {
  applicationsMock,
  resetApplicationsMock,
} from "@/mocks/handlers/applications"
import { LAYOUT_KEY } from "./use-layout-preference"

const column = (title: string) =>
  screen.getByRole("listitem", { name: new RegExp(`^${title},`) })
const stageOf = (employer: string) =>
  applicationsMock().apps.find((a) => a.employer === employer)!.stage

beforeEach(() => resetApplicationsMock())

describe("Applications board", () => {
  it("refuses an illegal move and explains it", async () => {
    const user = userEvent.setup()
    renderApp("/applications")
    const card = await screen.findByRole("button", {
      name: /Luangwa Re, Pricing Actuary/,
    })
    card.focus()
    // Tailoring -> Ready is set by approving the packet, not by dragging.
    await user.keyboard("{ArrowRight}")
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(/can't move to Ready/i)
    expect(alert).toHaveTextContent(/approve/i)
    expect(stageOf("Luangwa Re")).toBe("tailoring")
    expect(
      within(column("Tailoring")).getByText("Luangwa Re")
    ).toBeInTheDocument()
  })

  it("moves a card on a legal move", async () => {
    const user = userEvent.setup()
    renderApp("/applications")
    const card = await screen.findByRole("button", {
      name: /Kafue Analytics, Head of Data/,
    })
    card.focus()
    await user.keyboard("{ArrowRight}")
    await waitFor(() => expect(stageOf("Kafue Analytics")).toBe("tailoring"))
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("opens I applied myself for a drag to Submitted and does not change the stage", async () => {
    const user = userEvent.setup()
    renderApp("/applications")
    const card = await screen.findByRole("button", {
      name: /Kariba Freight, Head of Analytics/,
    })
    expect(stageOf("Kariba Freight")).toBe("submitted_unconfirmed")
    card.focus()
    await user.keyboard("{ArrowRight}")
    const dialog = await screen.findByRole("dialog", {
      name: /I applied myself/i,
    })
    expect(within(dialog).getByLabelText(/date applied/i)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/reference/i)).toBeInTheDocument()
    expect(stageOf("Kariba Freight")).toBe("submitted_unconfirmed")
    // Cancelling records nothing.
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    expect(stageOf("Kariba Freight")).toBe("submitted_unconfirmed")
  })

  it("records the owner's own submission through the dialog", async () => {
    const user = userEvent.setup()
    renderApp("/applications")
    const card = await screen.findByRole("button", {
      name: /Kariba Freight, Head of Analytics/,
    })
    card.focus()
    await user.keyboard("{ArrowRight}")
    const dialog = await screen.findByRole("dialog", {
      name: /I applied myself/i,
    })
    await user.type(within(dialog).getByLabelText(/reference/i), "KF-2041")
    await user.click(
      within(dialog).getByRole("button", { name: /record that i applied/i })
    )
    await waitFor(() => expect(stageOf("Kariba Freight")).toBe("submitted"))
  })

  it("filters by text", async () => {
    const user = userEvent.setup()
    renderApp("/applications")
    await screen.findByRole("button", { name: /Kafue Analytics/ })
    await user.type(screen.getByLabelText("Search applications"), "brewing")
    expect(
      screen.queryByRole("button", { name: /Kafue Analytics/ })
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Ndola Brewing/ })
    ).toBeInTheDocument()
  })
})

describe("Board and table toggle", () => {
  it("remembers the layout per device", async () => {
    const user = userEvent.setup()
    const first = renderApp("/applications")
    await screen.findByRole("button", { name: /Kafue Analytics/ })
    await user.click(screen.getByRole("radio", { name: /table/i }))
    expect(await screen.findByRole("table")).toBeInTheDocument()
    expect(localStorage.getItem(LAYOUT_KEY)).toBe("table")
    first.unmount()

    renderApp("/applications")
    expect(await screen.findByRole("table")).toBeInTheDocument()
    expect(screen.getByRole("radio", { name: /table/i })).toBeChecked()

    await user.click(screen.getByRole("radio", { name: /board/i }))
    expect(localStorage.getItem(LAYOUT_KEY)).toBe("board")
  })

  it("opens the quick look from a table row with a link to the job page", async () => {
    localStorage.setItem(LAYOUT_KEY, "table")
    const user = userEvent.setup()
    renderApp("/applications")
    await user.click(await screen.findByText("Kasama Capital"))
    const drawer = await screen.findByRole("dialog")
    const link = within(drawer).getByRole("link", { name: /full job page/i })
    expect(link).toHaveAttribute("href", expect.stringMatching(/^\/jobs\//))
    expect(await within(drawer).findByText(/Last events/i)).toBeInTheDocument()
  })
})

describe("Applications drill-through from Insights", () => {
  it("narrows to the link's filters, shows one chip each, removes one and clears all", async () => {
    const user = userEvent.setup()
    const { router } = renderApp(
      "/applications?reached=offer&channel=email&since=2026-11-01"
    )
    const bar = await screen.findByRole("group", {
      name: "Filters from Insights",
    })
    expect(within(bar).getByText("Step: Reached offer")).toBeInTheDocument()
    expect(within(bar).getByText("Channel: Email")).toBeInTheDocument()
    expect(within(bar).getByText("From 2026-11-01")).toBeInTheDocument()
    const offers = applicationsMock().apps.filter(
      (a) => ["offer", "accepted"].includes(a.stage) && a.channel === "email"
    )
    expect(offers.length).toBeGreaterThan(0)
    await screen.findByText(new RegExp(offers[0].employer))
    expect(screen.queryByText("Luangwa Re")).toBeNull() // tailoring: not an offer

    await user.click(
      within(bar).getByRole("button", { name: "Remove Channel: Email" })
    )
    await waitFor(() =>
      expect(router.state.location.search).not.toHaveProperty("channel")
    )
    expect(router.state.location.search).toMatchObject({ reached: "offer" })

    await user.click(within(bar).getByRole("button", { name: "Clear all" }))
    await waitFor(() =>
      expect(
        screen.queryByRole("group", { name: "Filters from Insights" })
      ).toBeNull()
    )
    expect(await screen.findAllByText("Luangwa Re")).not.toHaveLength(0)
  })
})
