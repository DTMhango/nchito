import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp, renderWithTheme } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import type { PendingAction } from "@/features/applications/api"
import { HandoffDetail } from "./handoff-page"
import {
  blockerKind,
  continueRule,
  resolveBody,
  siblingsOf,
  waitingText,
} from "./logic"
import type { BlockerKind } from "./w3-pending-types"

const signIns = () =>
  applicationsMock().actions.filter((a) => a.type === "sign_in")

const action = (
  blocker: BlockerKind,
  type: PendingAction["type"] = "sign_in"
) =>
  ({
    ...signIns()[0],
    type,
    detail: { ...signIns()[0].detail, blocker },
  }) as PendingAction

describe("portal accounts", () => {
  it("lists status, email used, last sign-in and applications waiting", async () => {
    renderApp("/accounts")
    const list = await screen.findByRole("list", { name: "Portal accounts" })
    const zambezi = within(list)
      .getByText("Zambezi Mining careers")
      .closest("li")!
    expect(within(zambezi).getByText("No account yet")).toBeInTheDocument()
    expect(
      within(zambezi).getByText("2 applications waiting")
    ).toBeInTheDocument()
    const kafue = within(list)
      .getByText("Kafue Analytics careers")
      .closest("li")!
    expect(
      within(kafue).getByText("Signed in on Office PC")
    ).toBeInTheDocument()
    expect(within(kafue).getByText(/chanda@example\.com/)).toBeInTheDocument()
  })

  it("has no password field on the list, the add form, the edit form or the handoff", async () => {
    const user = userEvent.setup()
    const { container } = renderApp("/accounts")
    await screen.findByRole("list", { name: "Portal accounts" })
    await user.click(screen.getByRole("button", { name: /add a portal/i }))
    await screen.findByRole("form", { name: "Add a portal" })
    expect(container.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByLabelText(/password/i)).toBeNull()
    await user.click(screen.getByRole("button", { name: "Cancel" }))
    await user.click(
      screen.getByRole("button", { name: "Edit Kafue Analytics careers" })
    )
    await screen.findByRole("form", { name: "Edit portal" })
    expect(container.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByLabelText(/password/i)).toBeNull()
  })

  it("handoff screen has no password field either", async () => {
    const { container } = renderApp(`/accounts/handoff/${signIns()[0].id}`)
    await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(container.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByLabelText(/password/i)).toBeNull()
  })

  it("adds a portal", async () => {
    const user = userEvent.setup()
    renderApp("/accounts")
    await screen.findByRole("list", { name: "Portal accounts" })
    await user.click(screen.getByRole("button", { name: /add a portal/i }))
    await user.type(screen.getByLabelText("Portal name"), "Mulungushi careers")
    await user.type(
      screen.getByLabelText("Portal link"),
      "https://mulungushi.example/jobs"
    )
    await user.click(screen.getByRole("button", { name: "Save portal" }))
    expect(await screen.findByText("Mulungushi careers")).toBeInTheDocument()
  })
})

describe("which blockers can continue", () => {
  it("offers continue only for kinds the owner can clear", () => {
    const can: BlockerKind[] = [
      "sign_in",
      "create_account",
      "captcha",
      "email_verification",
      "two_factor",
      "assessment",
    ]
    const cannot: BlockerKind[] = [
      "declaration",
      "unsupported_form",
      "off_domain_redirect",
    ]
    for (const k of can) expect(continueRule(k)).not.toBeNull()
    for (const k of cannot) expect(continueRule(k)).toBeNull()
    expect(continueRule(null)).toBeNull()
    expect(() => resolveBody("continue", "unsupported_form")).toThrow()
    expect(resolveBody("skip", "unsupported_form")).toMatchObject({
      resolution: "dismissed",
    })
  })

  it("labels the three continue buttons as asked", () => {
    expect(continueRule("sign_in")!.label).toBe("I've signed in, continue")
    expect(continueRule("create_account")!.label).toBe(
      "I created the account, continue"
    )
    expect(continueRule("captcha")!.label).toBe("I solved it, continue")
    expect(continueRule("email_verification")!.label).toBe(
      "I solved it, continue"
    )
  })

  it("renders Continue for a CAPTCHA and not for an unsupported form", () => {
    const { unmount } = renderWithTheme(
      <HandoffDetail action={action("captcha", "captcha")} siblings={[]} />
    )
    expect(
      screen.getByRole("button", { name: "I solved it, continue" })
    ).toBeInTheDocument()
    unmount()
    renderWithTheme(
      <HandoffDetail action={action("unsupported_form")} siblings={[]} />
    )
    expect(screen.queryByRole("button", { name: /continue/i })).toBeNull()
    expect(
      screen.getByRole("button", { name: "Apply myself instead" })
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Skip" })).toBeInTheDocument()
  })

  it("reads the kind from the detail first, then the action type", () => {
    expect(blockerKind(action("two_factor"))).toBe("two_factor")
    const plain = { ...signIns()[0], detail: {} } as PendingAction
    expect(blockerKind(plain)).toBe("sign_in")
    expect(
      blockerKind({ ...plain, type: "follow_up" } as PendingAction)
    ).toBeNull()
  })
})

describe("sign-in handoff", () => {
  it("tells the owner where, what is waiting and by when", async () => {
    renderApp(`/accounts/handoff/${signIns()[0].id}`)
    const card = await screen.findByRole("region", { name: "Sign-in handoff" })
    expect(
      within(card).getByText("2 applications are waiting.")
    ).toBeInTheDocument()
    expect(
      within(card).getByText(/Chrome, profile Job search/)
    ).toBeInTheDocument()
    expect(within(card).getByText(/Office PC/)).toBeInTheDocument()
    expect(
      within(card).getByRole("link", {
        name: /careers\.zambezi-mining\.example/,
      })
    ).toHaveAttribute("href", "https://careers.zambezi-mining.example/login")
    expect(within(card).getByText(/Due in/)).toBeInTheDocument()
    expect(within(card).getByText(/1 sent, next on/)).toBeInTheDocument()
  })

  it("continue resolves every waiting application and shows the tasks resuming on the same runner", async () => {
    const user = userEvent.setup()
    renderApp(`/accounts/handoff/${signIns()[0].id}`)
    await user.click(
      await screen.findByRole("button", { name: "I've signed in, continue" })
    )
    expect(await screen.findByText(/Resuming on Office PC/)).toBeInTheDocument()
    await waitFor(() => {
      for (const a of signIns()) {
        expect(a.status).toBe("resolved")
        expect(a.resolution).toMatchObject({
          resolution: "continue",
          note: "signed_in",
        })
      }
    })
    expect(await screen.findAllByText("Running")).toHaveLength(2)
    expect(screen.getByText(/still needs a submit permit/i)).toBeInTheDocument()
  })

  it("Apply myself and Skip close the action without resuming the agent", async () => {
    const user = userEvent.setup()
    renderApp(`/accounts/handoff/${signIns()[0].id}`)
    await user.click(
      await screen.findByRole("button", { name: "Apply myself instead" })
    )
    await waitFor(() => expect(signIns()[0].status).toBe("dismissed"))
    expect(signIns()[0].resolution).toMatchObject({ note: "apply_myself" })
    expect(screen.queryByText(/Resuming on/)).toBeNull()
  })

  it("is offered from Today", async () => {
    const id = signIns()[0].id
    renderApp("/today")
    const links = await screen.findAllByRole("link", { name: "Details" })
    expect(
      links.some((l) => l.getAttribute("href") === `/accounts/handoff/${id}`)
    ).toBe(true)
  })

  it("is offered from the Autopilot pending panel", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: /waiting/i }))
    const more = await screen.findAllByRole("link", {
      name: "Details and other choices",
    })
    expect(more.length).toBeGreaterThan(0)
  })

  it("says plainly when the link no longer points at anything", async () => {
    renderApp("/accounts/handoff/00000000-0000-4000-8000-000000000000")
    expect(
      await screen.findByText("That request is not available")
    ).toBeInTheDocument()
  })
})

describe("logic", () => {
  it("groups siblings by group key and words the count", () => {
    const [a, b] = signIns()
    expect(
      siblingsOf(a, [a, b])
        .map((x) => x.id)
        .sort()
    ).toEqual([a.id, b.id].sort())
    expect(waitingText(1)).toBe("1 application is waiting.")
    expect(waitingText(2)).toBe("2 applications are waiting.")
  })
})
