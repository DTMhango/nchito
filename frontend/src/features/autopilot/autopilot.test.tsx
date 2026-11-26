import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { autopilotMock } from "@/mocks/handlers/autopilot"
import {
  approvalStanding,
  autoVerdict,
  canCancel,
  dispatchView,
  gateState,
  shortHash,
  validateLimit,
} from "./logic"
import type { PacketOut } from "./api"

const appId = (employer: string) =>
  applicationsMock().apps.find((a) => a.employer === employer)!.id

describe("gates: unknown is never a pass", () => {
  it("reads missing, malformed and unknown results as not passing", () => {
    expect(gateState(undefined)).toBe("unknown")
    expect(gateState(null)).toBe("unknown")
    expect(gateState({ gate: "x" })).toBe("unknown")
    expect(gateState({ gate: "x", passed: undefined })).toBe("unknown")
    expect(
      gateState({ gate: "x", passed: true, detail: "Unknown: stale" })
    ).toBe("unknown")
    expect(
      gateState({ gate: "x", passed: false, detail: "Unknown: stale" })
    ).toBe("unknown")
    expect(
      gateState({ gate: "x", passed: false, detail: "Over the cap" })
    ).toBe("fail")
    expect(gateState({ gate: "x", passed: true })).toBe("pass")
  })

  it("cannot go automatically unless every gate clearly passed", () => {
    expect(autoVerdict([]).canAuto).toBe(false)
    expect(
      autoVerdict([
        { gate: "a", passed: true, detail: null },
        { gate: "b", passed: false, detail: "Unknown: not checked" },
      ]).canAuto
    ).toBe(false)
    expect(
      autoVerdict([{ gate: "a", passed: true, detail: null }]).canAuto
    ).toBe(true)
  })

  it("renders an unknown gate as Unknown and never as Passed", async () => {
    renderApp(`/approvals/${appId("Zambezi Mining Systems")}`)
    const gates = await screen.findByRole("region", {
      name: "Automatic sending checks",
    })
    const roleOpen = within(gates)
      .getByText("Role confirmed open recently")
      .closest("li")!
    expect(roleOpen).toHaveAttribute("data-state", "unknown")
    expect(within(roleOpen).getByText("Unknown")).toBeInTheDocument()
    expect(within(roleOpen).queryByText("Passed")).not.toBeInTheDocument()
    expect(
      within(gates).getByText(
        /needs your approval and will not go automatically/i
      )
    ).toBeInTheDocument()
  })
})

describe("approval and packet change", () => {
  const packet = (over: Partial<PacketOut>): PacketOut =>
    ({
      id: "p",
      version: 1,
      content_hash: "a".repeat(64),
      approved_at: null,
      approved_by: null,
      invalidated_at: null,
      invalidated_reason: null,
      ...over,
    }) as PacketOut

  it("an invalidated earlier approval does not cover the new version", () => {
    const standing = approvalStanding([
      packet({
        version: 1,
        approved_at: "2026-11-25T08:00:00Z",
        invalidated_at: "2026-11-25T09:00:00Z",
        invalidated_reason: "Answer changed.",
      }),
      packet({ version: 2, content_hash: "b".repeat(64) }),
    ])
    expect(standing.kind).toBe("invalidated")
    expect(
      approvalStanding([
        packet({ version: 2, approved_at: "2026-11-26T08:00:00Z" }),
      ]).kind
    ).toBe("approved")
    expect(shortHash("a3f9c21e5b7d4086".repeat(4))).toBe("#".concat("a3f9c21e"))
  })

  it("shows that the earlier approval no longer applies, with what changed", async () => {
    renderApp(`/approvals/${appId("Zambezi Mining Systems")}`)
    const banner = await screen.findByTestId("approval-invalidated")
    expect(banner).toHaveTextContent("Your earlier approval no longer applies")
    expect(banner).toHaveTextContent("#".concat("a3f9c21e"))
    expect(banner).toHaveTextContent("Notice period")
    const changed = screen.getByRole("region", {
      name: "Changed since you last looked",
    })
    expect(within(changed).getByText(/3 months/)).toBeInTheDocument()
    // The new version is not approved, so the approve action is open.
    expect(
      screen.getByRole("button", { name: "Let the agent submit" })
    ).toBeEnabled()
  })

  it("refuses to approve a version that changed after it was opened", async () => {
    const user = userEvent.setup()
    const id = appId("Zambezi Mining Systems")
    renderApp(`/approvals/${id}`)
    const button = await screen.findByRole("button", {
      name: "Let the agent submit",
    })
    // The packet changes on the server while the owner is reading.
    const current = autopilotMock().packets[id].at(-1)!
    current.version = 3
    current.content_hash = "c".repeat(64)
    await user.click(button)
    expect(
      await screen.findByText(/packet changed since you opened it/i)
    ).toBeInTheDocument()
    expect(current.approved_at).toBeNull()
  })

  it("approves the exact version shown", async () => {
    const user = userEvent.setup()
    const id = appId("Zambezi Mining Systems")
    renderApp(`/approvals/${id}`)
    await user.click(
      await screen.findByRole("button", { name: "Let the agent submit" })
    )
    await waitFor(() =>
      expect(autopilotMock().packets[id].at(-1)!.approved_at).not.toBeNull()
    )
  })
})

describe("dispatch: no retry on uncertain", () => {
  it("maps statuses and only lets a queued send be cancelled", () => {
    const base = { provider_message_id: null, error: null, send_after: null }
    expect(dispatchView({ ...base, status: "unknown" }).kind).toBe("uncertain")
    expect(dispatchView({ ...base, status: "sent" }).kind).toBe("uncertain")
    expect(
      dispatchView({ ...base, status: "sent", provider_message_id: "<m1>" })
        .kind
    ).toBe("sent")
    expect(canCancel(dispatchView({ ...base, status: "unknown" }))).toBe(false)
    expect(canCancel(dispatchView({ ...base, status: "reserved" }))).toBe(true)
  })

  it("explains uncertain with the reconcile action and offers no retry", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: "Sending" }))
    const card = await screen.findByRole("listitem", {
      name: /Head of Analytics, Kariba Freight/,
    })
    expect(await within(card).findByText("Uncertain")).toBeInTheDocument()
    expect(
      within(card).getByText(/never sent again automatically/i)
    ).toBeInTheDocument()
    expect(within(card).getByText(/To reconcile:/)).toBeInTheDocument()
    expect(
      within(card).getByRole("button", { name: /I checked: it arrived/i })
    ).toBeInTheDocument()
    for (const name of [/retry/i, /resend/i, /send again/i, /try again/i])
      expect(within(card).queryByRole("button", { name })).toBeNull()
    // Only a queued send can be cancelled.
    expect(
      within(card).queryByRole("button", { name: /cancel send/i })
    ).toBeNull()
  })

  it("shows sent attempts with their proof", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: "Sending" }))
    const card = await screen.findByRole("listitem", {
      name: /Director of Data Science, Lusaka Fintech Co/,
    })
    expect(await within(card).findByText("Acknowledged")).toBeInTheDocument()
    expect(
      within(card).getByText("<msg-4821@mail.example.com>")
    ).toBeInTheDocument()
  })
})

describe("master pause", () => {
  it("states the pause plainly and lists what it did", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    const pause = await screen.findByRole("region", { name: "Master pause" })
    expect(
      within(pause).getByText("Automatic sending is on")
    ).toBeInTheDocument()
    await user.click(
      within(pause).getByRole("button", {
        name: "Pause all automatic sending",
      })
    )
    expect(
      await within(pause).findByText("All automatic sending is paused")
    ).toBeInTheDocument()
    expect(within(pause).getByText(/activity log/i)).toBeInTheDocument()
    expect(
      within(pause).getByRole("button", { name: "Resume automatic sending" })
    ).toBeInTheDocument()
    await user.click(
      within(pause).getByRole("button", { name: "Resume automatic sending" })
    )
    expect(
      await within(pause).findByText("Automatic sending is on")
    ).toBeInTheDocument()
  })
})

describe("limits editor", () => {
  it("validates at a non-default value and keeps the rules between caps", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    const daily = await screen.findByLabelText("Applications a day, at most")
    const weekly = screen.getByLabelText("Applications a week, at most")
    expect(
      screen.getByText(/Effective: 5 .*Default/, { selector: "p" })
    ).toBeInTheDocument()

    // A valid non-default value saves, and then says it came from the owner.
    await user.clear(daily)
    await user.type(daily, "8")
    await user.click(
      within(
        screen.getByRole("form", { name: "Applications a day, at most, limit" })
      ).getByRole("button", { name: "Save" })
    )
    await waitFor(() =>
      expect(
        screen.getByText(/Effective: 8 .*Set by you.*default 5/)
      ).toBeInTheDocument()
    )

    // The daily cap cannot go above the weekly cap.
    await user.clear(daily)
    await user.type(daily, "25")
    await user.click(
      within(
        screen.getByRole("form", { name: "Applications a day, at most, limit" })
      ).getByRole("button", { name: "Save" })
    )
    expect(
      await screen.findByText(
        "The daily cap can't be above the weekly cap (20)."
      )
    ).toBeInTheDocument()

    // Nor the weekly cap below the new daily cap; and bounds from the registry apply.
    await user.clear(weekly)
    await user.type(weekly, "7")
    await user.click(
      within(
        screen.getByRole("form", {
          name: "Applications a week, at most, limit",
        })
      ).getByRole("button", { name: "Save" })
    )
    expect(
      await screen.findByText(
        "The weekly cap can't be below the daily cap (8)."
      )
    ).toBeInTheDocument()
  })

  it("checks bounds, whole numbers and times", () => {
    const daily = {
      key: "automation.daily_cap",
      kind: "int",
      minimum: 0,
      maximum: 100,
      label: "Daily cap",
    }
    const values = { "automation.daily_cap": 5, "automation.weekly_cap": 20 }
    expect(validateLimit(daily, "12", values)).toEqual({ ok: true, value: 12 })
    expect(validateLimit(daily, "101", values).ok).toBe(false)
    expect(validateLimit(daily, "2.5", values).ok).toBe(false)
    expect(validateLimit(daily, "", values).ok).toBe(false)
    const time = {
      key: "automation.quiet_hours_start",
      kind: "time",
      label: "x",
    }
    expect(validateLimit(time, "22:30", {}).ok).toBe(true)
    expect(validateLimit(time, "25:00", {}).ok).toBe(false)
  })
})

describe("handoff, pending actions and trusted sites", () => {
  it("gives the apply-yourself kit for an owner-channel role", async () => {
    const user = userEvent.setup()
    renderApp(`/approvals/${appId("Chambeshi Insurance")}`)
    const kit = await screen.findByRole("region", { name: "Apply yourself" })
    expect(
      await within(kit).findByRole("link", { name: "Open the posting" })
    ).toHaveAttribute("href", expect.stringContaining("chambeshi-insurance"))
    expect(within(kit).getByRole("link", { name: "cv" })).toHaveAttribute(
      "download"
    )
    await user.click(within(kit).getByRole("button", { name: "I applied" }))
    expect(
      await screen.findByRole("heading", { name: "I applied myself" })
    ).toBeInTheDocument()
    // Owner channel: Nchito offers no send button of its own.
    expect(
      screen.queryByRole("button", { name: /let the agent submit|send email/i })
    ).toBeNull()
  })

  it("resolves a sign-in with continue and an unknown question with an answer", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: /Waiting on you/ }))
    const signIn = (
      await screen.findAllByRole("listitem", {
        name: "Sign in to the Zambezi Mining careers portal",
      })
    )[0]
    await user.click(
      within(signIn).getByRole("button", { name: "I've signed in, continue" })
    )
    await waitFor(() =>
      expect(
        applicationsMock().actions.filter(
          (a) => a.type === "sign_in" && a.status === "resolved"
        )
      ).toHaveLength(1)
    )
    const question = (
      await screen.findAllByRole("listitem", {
        name: "Do you have the right to work in Kenya?",
      })
    )[0]
    await user.selectOptions(
      within(question).getByLabelText("Your answer"),
      "No"
    )
    // A material answer defaults to "this application only".
    expect(within(question).getByLabelText("Use this answer for")).toHaveValue(
      "this_application"
    )
    await user.click(
      within(question).getByRole("button", { name: "Save answer" })
    )
    await waitFor(() =>
      expect(
        applicationsMock().actions.filter(
          (a) => a.type === "unknown_question" && a.status === "resolved"
        )
      ).toHaveLength(1)
    )
  })

  it("adds and removes a trusted site, rejecting a malformed domain", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: "Trusted sites" }))
    const input = await screen.findByLabelText("Domain")
    await user.type(input, "not a domain")
    await user.click(screen.getByRole("button", { name: "Trust this site" }))
    expect(await screen.findByText(/enter a domain/i)).toBeInTheDocument()
    await user.clear(input)
    await user.type(input, "https://Careers.Example.com/jobs")
    await user.click(screen.getByRole("button", { name: "Trust this site" }))
    expect(await screen.findByText("careers.example.com")).toBeInTheDocument()
    await user.click(
      screen.getByRole("button", { name: "Stop trusting careers.example.com" })
    )
    await waitFor(() =>
      expect(screen.queryByText("careers.example.com")).not.toBeInTheDocument()
    )
  })
})
