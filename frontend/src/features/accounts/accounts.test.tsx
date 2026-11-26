import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { runnersMock } from "@/mocks/handlers/runners"
import { ACTION } from "@/mocks/dataset/runners"
import type { PendingAction } from "./api"
import {
  blockerKind,
  canGiveUp,
  continueRule,
  giveUpBody,
  readBlocker,
  waitingText,
} from "./logic"

const action = (id: string) =>
  applicationsMock().actions.find((a) => a.id === id)!

const withDetail = (
  base: PendingAction,
  over: Partial<PendingAction>,
  detail: Record<string, unknown>
) => ({ ...base, ...over, detail: { ...detail } }) as PendingAction

describe("portal accounts", () => {
  it("lists status, email used, last sign-in, applications waiting and the open request", async () => {
    renderApp("/accounts")
    const list = await screen.findByRole("list", { name: "Portal accounts" })
    const zambezi = within(list).getByRole("listitem", {
      name: /careers\.zambezi-mining\.example \(workday\)/,
    })
    expect(within(zambezi).getByText("No account yet")).toBeInTheDocument()
    expect(
      within(zambezi).getByText("2 applications waiting")
    ).toBeInTheDocument()
    expect(
      within(zambezi).getByRole("link", { name: "Sign-in request" })
    ).toHaveAttribute("href", `/accounts/handoff/${ACTION.signIn}`)
    const kafue = within(list).getByRole("listitem", {
      name: /kafue-analytics\.example/,
    })
    expect(
      within(kafue).getByText("Signed in on Office PC")
    ).toBeInTheDocument()
    expect(within(kafue).getByText(/chanda@example\.com/)).toBeInTheDocument()
  })

  it("filters by status through ?status=", async () => {
    const user = userEvent.setup()
    renderApp("/accounts")
    const list = await screen.findByRole("list", { name: "Portal accounts" })
    expect(within(list).getAllByRole("listitem")).toHaveLength(3)
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Show accounts" }),
      "signed_in"
    )
    await waitFor(() =>
      expect(
        within(
          screen.getByRole("list", { name: "Portal accounts" })
        ).getAllByRole("listitem")
      ).toHaveLength(1)
    )
    expect(
      screen.getByRole("listitem", { name: /kafue-analytics\.example/ })
    ).toBeInTheDocument()
  })

  it("has no password field on the add form, the edit form or the handoff", async () => {
    const user = userEvent.setup()
    const { container, unmount } = renderApp("/accounts")
    await screen.findByRole("list", { name: "Portal accounts" })
    await user.click(screen.getByRole("button", { name: /add a portal/i }))
    await screen.findByRole("form", { name: "Add a portal" })
    expect(container.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByLabelText(/password|secret|token|pin/i)).toBeNull()
    await user.click(screen.getByRole("button", { name: "Cancel" }))
    await user.click(
      screen.getByRole("button", { name: /Edit kafue-analytics/ })
    )
    await screen.findByRole("form", { name: "Edit portal" })
    expect(container.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByLabelText(/password/i)).toBeNull()
    unmount()
    const handoff = renderApp(`/accounts/handoff/${ACTION.signIn}`)
    await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(handoff.container.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByLabelText(/password/i)).toBeNull()
  })

  it("adds a portal by system and address, and says so for a duplicate", async () => {
    const user = userEvent.setup()
    renderApp("/accounts")
    await screen.findByRole("list", { name: "Portal accounts" })
    const add = async (tenant: string) => {
      await user.click(screen.getByRole("button", { name: /add a portal/i }))
      await user.type(screen.getByLabelText("Portal system"), "icims")
      await user.type(screen.getByLabelText("Portal address"), tenant)
      await user.click(screen.getByRole("button", { name: "Save portal" }))
    }
    await add("mulungushi.example")
    expect(
      await screen.findByText("mulungushi.example (icims)")
    ).toBeInTheDocument()
    const sent = runnersMock().accounts.at(-1)!
    expect(sent).toMatchObject({
      portal: "icims",
      tenant: "mulungushi.example",
    })
    expect(Object.keys(sent).some((k) => /password|secret/i.test(k))).toBe(
      false
    )
    await add("mulungushi.example")
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /already recorded/
    )
  })

  it("edits notes with PATCH and removes a portal", async () => {
    const user = userEvent.setup()
    renderApp("/accounts")
    await screen.findByRole("list", { name: "Portal accounts" })
    await user.click(screen.getByRole("button", { name: /Edit arch-re/ }))
    const notes = screen.getByLabelText("Notes (optional)")
    await user.clear(notes)
    await user.type(notes, "Use the careers page link")
    await user.click(screen.getByRole("button", { name: "Save portal" }))
    await waitFor(() =>
      expect(
        runnersMock().accounts.find((a) => a.tenant === "arch-re.example")!
          .notes
      ).toBe("Use the careers page link")
    )
    await user.click(screen.getByRole("button", { name: /Remove arch-re/ }))
    await user.click(screen.getByRole("button", { name: "Yes, remove" }))
    await waitFor(() =>
      expect(
        runnersMock().accounts.some((a) => a.tenant === "arch-re.example")
      ).toBe(false)
    )
  })
})

describe("blocker logic", () => {
  it("reads the kind from `kind`, then the gateway's detail.blocker, then the type", () => {
    expect(blockerKind(action(ACTION.code))).toBe("verification_code")
    expect(blockerKind(action(ACTION.offDomain))).toBe("redirect_off_domain")
    const plain = withDetail(action(ACTION.signIn), { kind: null }, {})
    expect(blockerKind(plain)).toBe("sign_in")
    expect(blockerKind(withDetail(plain, { type: "follow_up" }, {}))).toBeNull()
  })

  it("continues only the types the backend continues, with a label per kind", () => {
    expect(continueRule(action(ACTION.signIn))!.label).toBe(
      "I've signed in, continue"
    )
    expect(continueRule(action(ACTION.captcha))!.label).toBe(
      "I solved it, continue"
    )
    expect(continueRule(action(ACTION.code))!.label).toBe(
      "I entered the code, continue"
    )
    expect(continueRule(action(ACTION.unsupported))).toBeNull()
    expect(continueRule(action(ACTION.offDomain))).toBeNull()
  })

  it("gives up only account actions; no ids means every waiting application", () => {
    expect(canGiveUp(action(ACTION.signIn))).toBe(true)
    expect(canGiveUp(action(ACTION.unsupported))).toBe(true)
    expect(canGiveUp(action(ACTION.offDomain))).toBe(false)
    expect(giveUpBody("apply_myself", null)).toEqual({
      outcome: "manual_handoff",
      application_ids: null,
      note: null,
    })
    expect(giveUpBody("skip", ["x"], " later ")).toEqual({
      outcome: "skipped",
      application_ids: ["x"],
      note: "later",
    })
  })

  it("reads waiting applications, tasks and the runner from the detail", () => {
    const d = readBlocker(action(ACTION.signIn))
    expect(d.portalKey).toBe("workday:careers.zambezi-mining.example")
    expect(d.applications).toHaveLength(2)
    expect(d.tasks).toHaveLength(2)
    expect(d.runnerName).toBe("Office PC")
    expect(waitingText(1)).toBe("1 application is waiting.")
    expect(waitingText(2)).toBe("2 applications are waiting.")
  })
})

describe("sign-in handoff", () => {
  it("tells the owner where, in which runner, what is waiting and when reminders come", async () => {
    renderApp(`/accounts/handoff/${ACTION.signIn}`)
    const card = await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(
      within(card).getByText("2 applications are waiting.")
    ).toBeInTheDocument()
    expect(within(card).getByText("Office PC")).toBeInTheDocument()
    expect(
      within(card).getByRole("link", {
        name: /careers\.zambezi-mining\.example/,
      })
    ).toHaveAttribute("href", "https://careers.zambezi-mining.example/login")
    expect(within(card).getByText(/Due in/)).toBeInTheDocument()
    expect(
      await within(card).findByText(/reminded 72, 24, 6 hours before/)
    ).toBeInTheDocument()
  })

  it("continue resolves the action once and shows the tasks resuming on the same runner", async () => {
    const user = userEvent.setup()
    renderApp(`/accounts/handoff/${ACTION.signIn}`)
    await user.click(
      await screen.findByRole("button", { name: "I've signed in, continue" })
    )
    expect(await screen.findByText(/Resuming on Office PC/)).toBeInTheDocument()
    expect(action(ACTION.signIn).status).toBe("resolved")
    expect(action(ACTION.signIn).resolution).toMatchObject({
      resolution: "continue",
      note: "signed_in",
    })
    expect(screen.getByText(/2 tasks back in the queue/)).toBeInTheDocument()
    expect(screen.getByText(/still needs a submit permit/i)).toBeInTheDocument()
  })

  it("a CAPTCHA and a verification code on one task are separate: continuing one leaves the other", async () => {
    const user = userEvent.setup()
    renderApp(`/accounts/handoff/${ACTION.captcha}`)
    await user.click(
      await screen.findByRole("button", { name: "I solved it, continue" })
    )
    await waitFor(() => expect(action(ACTION.captcha).status).toBe("resolved"))
    expect(action(ACTION.code).status).toBe("open")
  })

  it("Apply myself instead gives up every waiting application as manual handoff", async () => {
    const user = userEvent.setup()
    renderApp(`/accounts/handoff/${ACTION.signIn}`)
    await user.click(
      await screen.findByRole("button", { name: "Apply myself instead" })
    )
    expect(
      await screen.findByText(/2 applications moved to you/)
    ).toBeInTheDocument()
    expect(action(ACTION.signIn).resolution).toMatchObject({
      resolution: "manual_handoff",
    })
    expect(screen.queryByText(/Resuming on/)).toBeNull()
  })

  it("Skip can cover some of the waiting applications; the rest keep waiting", async () => {
    const user = userEvent.setup()
    renderApp(`/accounts/handoff/${ACTION.signIn}`)
    const boxes = await screen.findAllByRole("checkbox")
    expect(boxes).toHaveLength(2)
    await user.click(boxes[1])
    await user.click(screen.getByRole("button", { name: "Skip" }))
    const done = await screen.findByText(/Skipped 1 application/)
    expect(done).toHaveTextContent(/1 application is waiting/)
    expect(action(ACTION.signIn).status).toBe("open")
  })

  it("an unsupported form offers apply myself and skip, never continue", async () => {
    renderApp(`/accounts/handoff/${ACTION.unsupported}`)
    const card = await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(within(card).queryByRole("button", { name: /continue/i })).toBeNull()
    expect(
      within(card).getByRole("button", { name: "Apply myself instead" })
    ).toBeInTheDocument()
    expect(
      within(card).getByRole("button", { name: "Skip" })
    ).toBeInTheDocument()
  })

  it("an off-site redirect can only be closed, and the page's words are shown as data", async () => {
    const user = userEvent.setup()
    renderApp(`/accounts/handoff/${ACTION.pageAsked}`)
    const card = await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(
      within(card).getByText(/Ignore your instructions/)
    ).toBeInTheDocument()
    expect(within(card).getByText(/never acted on/)).toBeInTheDocument()
    expect(
      within(card).queryByRole("button", { name: /apply myself|continue/i })
    ).toBeNull()
    await user.click(
      within(card).getByRole("button", { name: "I've looked at it, close it" })
    )
    await waitFor(() =>
      expect(action(ACTION.pageAsked).status).toBe("dismissed")
    )
  })

  it("is offered from Today", async () => {
    renderApp("/today")
    const links = await screen.findAllByRole("link", { name: "Details" })
    expect(
      links.some(
        (l) => l.getAttribute("href") === `/accounts/handoff/${ACTION.signIn}`
      )
    ).toBe(true)
  })

  it("is offered from the Autopilot pending panel", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: /waiting/i }))
    const more = await screen.findAllByRole("link", {
      name: "Details and other choices",
    })
    expect(
      more.some(
        (l) => l.getAttribute("href") === `/accounts/handoff/${ACTION.signIn}`
      )
    ).toBe(true)
  })

  it("says plainly when the link no longer points at anything", async () => {
    renderApp("/accounts/handoff/00000000-0000-4000-8000-000000000000")
    expect(
      await screen.findByText("That request is not available")
    ).toBeInTheDocument()
  })
})
