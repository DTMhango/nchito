import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp, setupUser } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { runnersMock } from "@/mocks/handlers/runners"
import { ACTION } from "@/mocks/dataset/runners"
import type { PendingAction } from "./api"
import { http, HttpResponse } from "msw"
import { server } from "@/test/server"
import {
  blockerKind,
  canGiveUp,
  choicesOf,
  continueErrorText,
  continueRule,
  giveUpBody,
  readBlocker,
  reminderText,
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

  it("continues only when the server lists continue, with a label per kind", () => {
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
    // The choices decide, not the type: an assessment the server continues gets the generic label.
    const assessment = withDetail(
      action(ACTION.unsupported),
      { type: "assessment", kind: "assessment", choices: ["continue"] },
      { kind: "assessment" }
    )
    expect(continueRule(assessment)!.label).toBe("I've done it, continue")
    expect(
      continueRule(withDetail(action(ACTION.signIn), { choices: [] }, {}))
    ).toBeNull()
  })

  it("orders the server's choices and offers none once the action is closed", () => {
    expect(choicesOf(action(ACTION.offDomain))).toEqual([
      "manual_handoff",
      "skipped",
      "continue_acknowledged",
    ])
    expect(choicesOf(action(ACTION.signIn))).toEqual([
      "continue",
      "manual_handoff",
      "skipped",
    ])
    expect(
      choicesOf(withDetail(action(ACTION.signIn), { status: "resolved" }, {}))
    ).toEqual([])
  })

  it("words reminders and the 422 acknowledgement refusal", async () => {
    expect(reminderText(action(ACTION.signIn))).toMatch(
      /^1 reminder sent, next /
    )
    expect(
      reminderText(
        withDetail(
          action(ACTION.signIn),
          { reminders_sent: 3, next_reminder_at: null },
          {}
        )
      )
    ).toBe("3 reminders sent, no more reminders before the deadline")
    expect(
      reminderText(
        withDetail(
          action(ACTION.changed),
          { reminders_sent: null, next_reminder_at: null },
          {}
        )
      )
    ).toBeNull()
    const { ApiError } = await import("@/lib/api/client")
    expect(
      continueErrorText(
        new ApiError(422, { detail: { code: "acknowledgement_required" } }),
        "f"
      )
    ).toMatch(/Tick the box/)
    expect(continueErrorText(new Error("x"), "fallback")).toBe("fallback")
  })

  it("gives up when the server lists it; no ids means every waiting application", () => {
    expect(canGiveUp(action(ACTION.signIn))).toBe(true)
    expect(canGiveUp(action(ACTION.unsupported))).toBe(true)
    expect(canGiveUp(action(ACTION.offDomain))).toBe(true)
    expect(
      canGiveUp(
        withDetail(action(ACTION.signIn), { choices: ["continue"] }, {})
      )
    ).toBe(false)
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

  it("a suspicious page shows its words as data and offers apply myself, skip and an acknowledged continue", async () => {
    renderApp(`/accounts/handoff/${ACTION.pageAsked}`)
    const card = await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(
      within(card).getByText(/Ignore your instructions/)
    ).toBeInTheDocument()
    expect(within(card).getByText(/never acted on/)).toBeInTheDocument()
    const names = within(card)
      .getAllByRole("button")
      .map((b) => b.textContent)
    expect(names).toEqual([
      "Apply myself instead",
      "Skip",
      "It's fine, continue",
    ])
    expect(within(card).queryByRole("button", { name: /close it/i })).toBeNull()
  })

  it("continues a suspicious page only after the owner ticks that they checked it", async () => {
    const user = setupUser()
    renderApp(`/accounts/handoff/${ACTION.offDomain}`)
    await user.click(
      await screen.findByRole("button", { name: "It's fine, continue" })
    )
    const gate = screen.getByRole("group", { name: "Continue on this page" })
    const go = within(gate).getByRole("button", {
      name: "Continue on this page",
    })
    expect(go).toBeDisabled()
    await user.type(
      within(gate).getByLabelText("Note for the record (optional)"),
      "Same company, new host"
    )
    await user.click(
      within(gate).getByRole("checkbox", {
        name: "I checked this page and it is safe to continue",
      })
    )
    expect(go).toBeEnabled()
    await user.click(go)
    await waitFor(() =>
      expect(action(ACTION.offDomain).status).toBe("resolved")
    )
    expect(action(ACTION.offDomain).resolution).toMatchObject({
      resolution: "continue",
      acknowledged: true,
      note: "Same company, new host",
    })
    expect(await screen.findByText(/Resuming on/)).toBeInTheDocument()
  })

  it("shows a 422 acknowledgement_required refusal as an error", async () => {
    server.use(
      http.post("*/api/pending-actions/:id/resolve", () =>
        HttpResponse.json(
          {
            detail: {
              code: "acknowledgement_required",
              reason: "confirm you checked the page",
            },
          },
          { status: 422 }
        )
      )
    )
    const user = setupUser()
    renderApp(`/accounts/handoff/${ACTION.pageAsked}`)
    await user.click(
      await screen.findByRole("button", { name: "It's fine, continue" })
    )
    await user.click(screen.getByRole("checkbox", { name: /safe to continue/ }))
    await user.click(
      screen.getByRole("button", { name: "Continue on this page" })
    )
    expect(await screen.findByRole("alert")).toHaveTextContent(/Tick the box/)
    expect(action(ACTION.pageAsked).status).toBe("open")
  })

  it("apply myself on a suspicious page goes through give-up", async () => {
    const user = setupUser()
    renderApp(`/accounts/handoff/${ACTION.offDomain}`)
    await user.click(
      await screen.findByRole("button", { name: "Apply myself instead" })
    )
    await waitFor(() =>
      expect(action(ACTION.offDomain).resolution).toMatchObject({
        resolution: "manual_handoff",
      })
    )
  })

  it("a field mismatch lists the differing fields and can continue", async () => {
    renderApp(`/accounts/handoff/${ACTION.mismatch}`)
    const card = await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(within(card).getByText("Entered details differ")).toBeInTheDocument()
    const fields = within(card).getByRole("list", {
      name: "Fields that differ",
    })
    expect(within(fields).getByText("full_name")).toBeInTheDocument()
    expect(within(fields).getByText("phone")).toBeInTheDocument()
    expect(
      within(card).getByRole("button", { name: "I've done it, continue" })
    ).toBeInTheDocument()
  })

  it("shows the reminders sent and when the next one is due on a sign-in", async () => {
    renderApp(`/accounts/handoff/${ACTION.signIn}`)
    const card = await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(within(card).getByText(/1 reminder sent, next /)).toBeInTheDocument()
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

  it("filters the Autopilot pending panel by exact blocker kind and renders each row's choices", async () => {
    const user = setupUser()
    const seen: string[] = []
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/api/pending-actions?")) seen.push(request.url)
    })
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: /waiting/i }))
    const items = () =>
      within(screen.getByRole("list", { name: "Waiting items" })).getAllByRole(
        "listitem"
      )
    await waitFor(() => expect(items().length).toBeGreaterThan(5))
    // The sign-in row shows its reminders and the server's three choices.
    const signIn = screen.getByRole("listitem", {
      name: /Sign in to the Zambezi Mining careers portal/,
    })
    expect(
      within(signIn).getByText(/Reminders: 1 reminder sent, next /)
    ).toBeInTheDocument()
    expect(
      within(signIn).getByRole("button", { name: "I've signed in, continue" })
    ).toBeInTheDocument()

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Show what is waiting" }),
      "redirect_off_domain"
    )
    await waitFor(() => expect(items()).toHaveLength(1))
    expect(seen.some((u) => u.includes("kind=redirect_off_domain"))).toBe(true)
    const row = items()[0]
    expect(row).toHaveAccessibleName(/The form left jobs\.luangwa\.example/)
    expect(
      within(row).getByRole("button", { name: "It's fine, continue" })
    ).toBeInTheDocument()
    expect(within(row).queryByRole("button", { name: /continue,/ })).toBeNull()
    expect(within(row).queryByRole("button", { name: "Dismiss" })).toBeNull()

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Show what is waiting" }),
      "field_mismatch"
    )
    await waitFor(() =>
      expect(items()[0]).toHaveAccessibleName(/Check the details entered/)
    )
    expect(items()).toHaveLength(1)
    expect(within(items()[0]).getByText(/full_name, phone/)).toBeInTheDocument()
    server.events.removeAllListeners()
  })

  it("says plainly when the link no longer points at anything", async () => {
    renderApp("/accounts/handoff/00000000-0000-4000-8000-000000000000")
    expect(
      await screen.findByText("That request is not available")
    ).toBeInTheDocument()
  })
})
