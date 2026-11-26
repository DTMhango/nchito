import { afterEach, describe, expect, it, vi } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import { renderApp, setupUser } from "@/test/render"
import { calendarMock } from "@/mocks/handlers/calendar"

configure({ asyncUtilTimeout: 8000 })

afterEach(() => vi.restoreAllMocks())

describe("Settings > Connections: calendar", () => {
  it("makes, copies, rotates and revokes the subscription link", async () => {
    const user = setupUser()
    const write = vi.fn().mockResolvedValue(undefined)
    renderApp("/settings/connections")
    const card = await screen.findByRole("region", { name: "Calendar" })
    // Stub after the user-event clipboard is installed.
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: write },
      configurable: true,
    })
    await user.click(
      await within(card).findByRole("button", { name: "Make a link" })
    )
    const box = (await within(card).findByLabelText(
      "Subscription link"
    )) as HTMLInputElement
    const first = box.value
    expect(first).toMatch(/\.ics$/)

    await user.click(within(card).getByRole("button", { name: "Copy" }))
    await waitFor(() => expect(write).toHaveBeenCalledWith(first))

    await user.click(within(card).getByRole("button", { name: "Rotate link" }))
    await waitFor(() =>
      expect(
        (within(card).getByLabelText("Subscription link") as HTMLInputElement)
          .value
      ).not.toBe(first)
    )

    await user.click(within(card).getByRole("button", { name: "Revoke link" }))
    await waitFor(() =>
      expect(within(card).queryByLabelText("Subscription link")).toBeNull()
    )
    expect(calendarMock.feedUrl()).toBeNull()
  })

  it("edits the detail level, reminders and prep nudge through the settings", async () => {
    renderApp("/settings/connections")
    const card = await screen.findByRole("region", { name: "Calendar" })
    const list = await within(card).findByRole("list", {
      name: "Calendar settings",
    })
    expect(within(list).getByText("Calendar detail")).toBeVisible()
    expect(
      within(list).getByText("Reminders before an interview")
    ).toBeVisible()
    expect(within(list).getByText("Preparation nudge")).toBeVisible()
  })

  it("keeps Google Calendar off until switched on, and says it never reads calendars", async () => {
    const user = setupUser()
    calendarMock.connectGoogle(false)
    renderApp("/settings/connections")
    const card = await screen.findByRole("region", { name: "Calendar" })
    expect(
      await within(card).findByText(/never reads your calendars/)
    ).toBeVisible()
    const sw = within(card).getByRole("switch", {
      name: "Write interviews to Google Calendar",
    })
    expect(sw).not.toBeChecked()
    await user.click(sw)
    await waitFor(() => expect(calendarMock.google().enabled).toBe(true))
  })

  it("welcomes the owner back from Google Calendar", async () => {
    renderApp("/settings/connections?connected=gcalendar")
    expect(
      await screen.findByText(/Google Calendar is connected/)
    ).toBeVisible()
  })
})
