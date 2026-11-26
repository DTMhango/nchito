import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it } from "vitest"
import { renderApp } from "@/test/render"
import {
  applicationsMock,
  resetApplicationsMock,
} from "@/mocks/handlers/applications"

beforeEach(() => resetApplicationsMock())

const open = () => applicationsMock().actions.filter((a) => a.status === "open")

describe("Today: Needs you", () => {
  it("groups decisions by shared blocker, with deadline and consequence", async () => {
    renderApp("/today")
    const needs = await screen.findByRole("region", { name: "Needs you" })
    expect(
      await within(needs).findByText(
        "One work-rights answer affects four roles"
      )
    ).toBeInTheDocument()
    expect(
      within(needs).getByText(
        "Signing in to this portal unlocks two applications"
      )
    ).toBeInTheDocument()
    // 4 questions + 2 sign-ins + approve + confirm collapse to 4 decisions.
    expect(open().length).toBe(8)
    expect(within(needs).getByText("4")).toBeInTheDocument()
    expect(within(needs).getAllByText(/paused until you answer/i).length).toBe(
      1
    )
    expect(
      within(needs).getAllByText(/Closes in \d+ days?\./).length
    ).toBeGreaterThan(0)
    // Each group has a primary and a secondary action.
    expect(
      within(needs).getByRole("button", { name: "Answer" })
    ).toBeInTheDocument()
    expect(
      within(needs).getByRole("button", { name: /skip these roles/i })
    ).toBeInTheDocument()
  })

  it("answers inline with the scope default from the question's materiality", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    await user.click(await screen.findByRole("button", { name: "Answer" }))
    const form = await screen.findByRole("form", {
      name: /answer the question/i,
    })
    // A work-rights question is material: the settings default is "this application only".
    await waitFor(() =>
      expect(
        within(form).getByRole("radio", { name: /this application only/i })
      ).toBeChecked()
    )
    await user.click(within(form).getByRole("combobox"))
    await user.click(await screen.findByRole("option", { name: "No" }))
    // The owner can widen it before saving.
    await user.click(within(form).getByRole("radio", { name: /this country/i }))
    await user.click(within(form).getByRole("button", { name: "Save answer" }))

    await waitFor(() =>
      expect(
        screen.queryByText("One work-rights answer affects four roles")
      ).not.toBeInTheDocument()
    )
    const answered = applicationsMock().actions.filter(
      (a) => a.type === "unknown_question"
    )
    expect(answered.every((a) => a.status === "resolved")).toBe(true)
  })

  it("lists the same pending actions in the bell", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    const bell = await screen.findByRole("button", {
      name: /notifications, 8 waiting/i,
    })
    await user.click(bell)
    expect(
      await screen.findByText("Approve the packet for Data Platform Lead", {
        selector: "span",
      })
    ).toBeInTheDocument()
  })
})
