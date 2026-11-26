import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { renderApp } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { ACTION } from "@/mocks/dataset/runners"

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
    // 4 questions + 1 tenant sign-in + approve + confirm + mail proposal + 6 wave 3 actions
    // collapse to 11 decisions.
    expect(open().length).toBe(14)
    expect(within(needs).getByText("11")).toBeInTheDocument()
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

  it("opens the pending action a link names, with its answer form ready", async () => {
    const question = open().find((a) => a.type === "unknown_question")!
    renderApp(`/today?action=${question.id}`)
    const needs = await screen.findByRole("region", { name: "Needs you" })
    const focused = await waitFor(() => {
      const el = needs.querySelector<HTMLElement>("[data-focused]")
      expect(el).not.toBeNull()
      return el!
    })
    expect(focused).toHaveAttribute("aria-current", "true")
    expect(
      within(focused).getByRole("form", { name: /answer the question/i })
    ).toBeInTheDocument()
    // only that decision opens
    expect(needs.querySelectorAll("[data-focused]")).toHaveLength(1)
  })

  it("says so when the linked action no longer waits", async () => {
    renderApp("/today?action=c0000000-0000-4000-8000-000000009999")
    expect(
      await screen.findByText(/That question is no longer waiting for you/)
    ).toBeInTheDocument()
  })

  it("lists the same pending actions in the bell", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    const bell = await screen.findByRole("button", {
      name: /notifications, 14 waiting/i,
    })
    await user.click(bell)
    expect(
      await screen.findByText("Approve the packet for Data Platform Lead", {
        selector: "span",
      })
    ).toBeInTheDocument()
  })

  it("links a posting change to the job's Changes tab and dismisses it", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    const needs = await screen.findByRole("region", { name: "Needs you" })
    const link = await within(needs).findByRole("link", {
      name: "See what changed",
    })
    const changed = open().find((a) => a.id === ACTION.changed)!
    expect(link).toHaveAttribute(
      "href",
      `/jobs/${String(changed.detail.job_id)}?tab=changes`
    )
    const row = link.closest("[class]")!.parentElement!
    await user.click(within(row).getByRole("button", { name: "Dismiss" }))
    await waitFor(() => expect(changed.status).toBe("dismissed"))
  })

  it("gives the new blocker types their own labels and only choices the backend accepts", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    const needs = await screen.findByRole("region", { name: "Needs you" })
    expect(
      await within(needs).findByRole("link", { name: "See where it went" })
    ).toHaveAttribute("href", `/accounts/handoff/${ACTION.offDomain}`)
    expect(
      within(needs).getByRole("link", { name: "See what the page asked" })
    ).toHaveAttribute("href", `/accounts/handoff/${ACTION.pageAsked}`)
    expect(
      within(needs).getByRole("link", { name: "Choose what to do" })
    ).toHaveAttribute("href", `/accounts/handoff/${ACTION.unsupported}`)
    expect(
      within(needs).getByRole("button", { name: "I entered the code" })
    ).toBeInTheDocument()
    // Closing a redirect is a dismissal; the backend refuses anything else for it.
    const closeButtons = within(needs).getAllByRole("button", {
      name: "Close it",
    })
    expect(closeButtons).toHaveLength(2)
    await user.click(closeButtons[0])
    await waitFor(() =>
      expect(
        applicationsMock().actions.filter(
          (a) =>
            (a.id === ACTION.offDomain || a.id === ACTION.pageAsked) &&
            a.status === "dismissed"
        )
      ).toHaveLength(1)
    )
  })

  it("continues a portal sign-in once, for every waiting application", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    const needs = await screen.findByRole("region", { name: "Needs you" })
    await user.click(
      await within(needs).findByRole("button", { name: "I've signed in" })
    )
    const signIn = applicationsMock().actions.find(
      (a) => a.id === ACTION.signIn
    )!
    await waitFor(() => expect(signIn.status).toBe("resolved"))
    expect(signIn.resolution).toMatchObject({
      resolution: "continue",
      resumed_tasks: expect.arrayContaining([expect.any(String)]),
    })
    // The CAPTCHA on another task is not touched.
    expect(
      applicationsMock().actions.find((a) => a.id === ACTION.captcha)!.status
    ).toBe("open")
  })

  it("bell items open the handoff, the Changes tab or Today", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    await user.click(
      await screen.findByRole("button", { name: /notifications, 14 waiting/i })
    )
    const links = await screen.findAllByRole("link")
    const hrefs = links.map((l) => l.getAttribute("href") ?? "")
    expect(hrefs).toContain(`/accounts/handoff/${ACTION.signIn}`)
    expect(hrefs.some((h) => h.includes("?tab=changes"))).toBe(true)
    expect(hrefs.some((h) => h.startsWith("/today?action="))).toBe(true)
  })

  it("sends a notification's /today?action= link for a blocker to its handoff page", async () => {
    const { router } = renderApp(`/today?action=${ACTION.captcha}`)
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/accounts/handoff/${ACTION.captcha}`
      )
    )
  })
})
