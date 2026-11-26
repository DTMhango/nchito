import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { applicationsMock } from "@/mocks/handlers/applications"
import { autopilotMock, enterRestoreMock } from "@/mocks/handlers/autopilot"
import {
  approvalStanding,
  autoVerdict,
  canCancel,
  dispatchView,
  gateState,
  deferredText,
  roleChoices,
  shortHash,
  validateLimit,
} from "./logic"
import type { GateResult, PacketOut } from "./api"

const appId = (employer: string) =>
  applicationsMock().apps.find((a) => a.employer === employer)!.id

describe("gates: unknown is never a pass", () => {
  it("reads the tri-state from outcome only; null, missing and unknown never pass", () => {
    expect(gateState(undefined)).toBe("unknown")
    expect(gateState(null)).toBe("unknown")
    expect(gateState({ gate: "x" })).toBe("unknown")
    // A null outcome is unknown even when the legacy flag says passed.
    expect(gateState({ gate: "x", passed: true, outcome: null })).toBe(
      "unknown"
    )
    expect(gateState({ gate: "x", passed: true, outcome: "unknown" })).toBe(
      "unknown"
    )
    expect(gateState({ gate: "x", passed: false, outcome: "fail" })).toBe(
      "fail"
    )
    // No string-prefix inference: the detail wording does not matter.
    expect(
      gateState({ gate: "x", passed: true, detail: "Unknown", outcome: "pass" })
    ).toBe("pass")
  })

  it("cannot go automatically unless every gate clearly passed", () => {
    const g = (
      gate: string,
      outcome: "pass" | "fail" | "unknown" | null
    ): GateResult => ({
      gate,
      passed: outcome === "pass",
      detail: null,
      outcome,
    })
    expect(autoVerdict([]).canAuto).toBe(false)
    expect(autoVerdict([g("a", "pass"), g("b", "unknown")]).canAuto).toBe(false)
    expect(autoVerdict([g("a", "pass"), g("b", null)]).canAuto).toBe(false)
    expect(autoVerdict([g("a", "pass")]).canAuto).toBe(true)
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

  it("shows an approval refusal plainly, with the gates that stopped it", async () => {
    const user = userEvent.setup()
    const id = appId("Zambezi Mining Systems")
    autopilotMock().refuseApproval = {
      code: "role_closed",
      reason: "role_open is unknown",
    }
    renderApp(`/approvals/${id}`)
    await user.click(
      await screen.findByRole("button", { name: "Let the agent submit" })
    )
    const msg = await screen.findByText("role_open is unknown")
    const alert = msg.closest<HTMLElement>("[role=alert]")!
    const stopped = within(alert)
      .getByText("Checks that stopped it")
      .closest<HTMLElement>("section")!
    expect(stopped).toHaveAttribute("aria-label", "Checks that stopped it")
    expect(
      within(stopped).getByText("Role confirmed open recently").closest("li")
    ).toHaveAttribute("data-state", "unknown")
    expect(autopilotMock().packets[id].at(-1)!.approved_at).toBeNull()
  })

  it("rejects through the reject endpoint, with an optional reason", async () => {
    const user = userEvent.setup()
    const id = appId("Zambezi Mining Systems")
    renderApp(`/approvals/${id}`)
    await user.click(await screen.findByRole("button", { name: "Reject" }))
    const form = screen.getByRole("form", { name: "Reject" })
    await user.type(within(form).getByRole("textbox"), "Too far to commute")
    await user.click(
      within(form).getByRole("button", { name: "Reject this role" })
    )
    await waitFor(() =>
      expect(autopilotMock().decisions).toEqual([
        { id, kind: "reject", text: "Too far to commute" },
      ])
    )
  })

  it("requests changes through its endpoint and needs a note", async () => {
    const user = userEvent.setup()
    const id = appId("Zambezi Mining Systems")
    renderApp(`/approvals/${id}`)
    await user.click(
      await screen.findByRole("button", { name: "Request changes" })
    )
    const form = screen.getByRole("form", { name: "Request changes" })
    await user.click(
      within(form).getByRole("button", { name: "Send back for changes" })
    )
    expect(await screen.findByText("Say what should change.")).toBeVisible()
    await user.type(within(form).getByRole("textbox"), "Shorter letter")
    await user.click(
      within(form).getByRole("button", { name: "Send back for changes" })
    )
    await waitFor(() =>
      expect(autopilotMock().decisions).toEqual([
        { id, kind: "changes", text: "Shorter letter" },
      ])
    )
  })

  it("says plainly when no packet has been built", async () => {
    const id = appId("Kafue Analytics")
    autopilotMock().packets[id] = []
    renderApp(`/approvals/${id}`)
    expect(
      await screen.findByText(/No packet has been built/i)
    ).toBeInTheDocument()
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
  it("maps statuses and only lets a waiting send be cancelled", () => {
    const base = { provider_message_id: null, error: null, send_after: null }
    expect(dispatchView({ ...base, status: "unknown" }).kind).toBe("uncertain")
    // The server's uncertain flag wins over any status.
    expect(
      dispatchView({ ...base, status: "handed_off", uncertain: true }).kind
    ).toBe("uncertain")
    expect(dispatchView({ ...base, status: "sent" }).evidence).toBeNull()
    expect(
      dispatchView({
        ...base,
        status: "sent",
        evidence: {
          kind: "reference",
          value: "REF-1",
          screenshot_ref: null,
          at: null,
        },
      }).evidence
    ).toBe("REF-1")
    expect(canCancel(dispatchView({ ...base, status: "unknown" }))).toBe(false)
    expect(canCancel(dispatchView({ ...base, status: "reserved" }))).toBe(true)
  })

  it("reads a quiet-hours deferral from the dispatch itself, as held, not failed", () => {
    const d = {
      status: "reserved" as const,
      send_after: "2026-11-27T05:00:00Z",
      deferred_reason: "quiet_hours" as const,
      deferred_until: "2026-11-27T05:00:00Z",
    }
    const now = new Date("2026-11-27T01:00:00Z")
    // the owner's zone: 05:00 UTC is 07:00 in Lusaka
    expect(deferredText(d, "Africa/Lusaka", now)).toBe(
      "Held for quiet hours until 07:00"
    )
    expect(
      deferredText(d, "Africa/Lusaka", new Date("2026-11-25T12:00:00Z"))
    ).toBe("Held for quiet hours until Fri 07:00")
    expect(
      deferredText({ ...d, deferred_reason: null }, "Africa/Lusaka")
    ).toBeNull()
    expect(
      deferredText({ ...d, status: "cancelled" }, "Africa/Lusaka")
    ).toBeNull()
    const v = dispatchView({ ...d, provider_message_id: null, error: null })
    expect(v.kind).toBe("postponed")
    expect(v.explain).toMatch(/^Held for quiet hours until /)
    expect(canCancel(v)).toBe(true)
    // a plain send delay is queued, not held
    expect(
      dispatchView({
        ...d,
        deferred_reason: null,
        provider_message_id: null,
        error: null,
      }).kind
    ).toBe("queued")
  })

  it("shows the postponed send on the Sending tab", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: "Sending" }))
    const card = await screen.findByRole("listitem", {
      name: /Principal Data Engineer, Nyika Labs/,
    })
    expect(
      await within(card).findByText(/Held for quiet hours until /)
    ).toBeInTheDocument()
    expect(within(card).queryByText("Failed")).toBeNull()
  })

  it("reconciles one uncertain attempt: check, then record it went out", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: "Sending" }))
    const card = await screen.findByRole("listitem", {
      name: /Head of Analytics, Kariba Freight/,
    })
    const id = appId("Kariba Freight")
    const attempt = autopilotMock().dispatches[id].find((d) => d.uncertain)!
    expect(await within(card).findByText(/Checked 2 times/)).toBeInTheDocument()
    await user.click(
      await within(card).findByRole("button", { name: "Check again now" })
    )
    await waitFor(() => expect(attempt.reconcile_attempts).toBe(3))
    expect(attempt.uncertain).toBe(true)
    await user.click(
      within(card).getByRole("button", { name: /I checked: it arrived/i })
    )
    await user.type(
      within(card).getByLabelText(/Reference or what you saw/),
      "KF-2291"
    )
    await user.click(
      within(card).getByRole("button", { name: "Record that it arrived" })
    )
    await waitFor(() => expect(attempt.status).toBe("sent"))
    expect(attempt.evidence?.value).toBe("KF-2291")
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

  it("records who paused it and why", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    const pause = await screen.findByRole("region", { name: "Master pause" })
    await user.type(
      within(pause).getByLabelText(/Reason for pausing/),
      "On leave this week"
    )
    await user.click(
      within(pause).getByRole("button", { name: "Pause all automatic sending" })
    )
    expect(await within(pause).findByText(/Paused by you/)).toBeInTheDocument()
    expect(within(pause).getByTestId("pause-reason")).toHaveTextContent(
      "Reason: On leave this week."
    )
  })

  it("after a restore, refuses the resume and lists what is outstanding", async () => {
    const user = userEvent.setup()
    // Build the Kariba attempts so the uncertain one exists before the restore.
    const id = appId("Kariba Freight")
    enterRestoreMock("2026-11-25T06:00:00Z")
    renderApp("/autopilot")
    const panel = await screen.findByRole("region", {
      name: "Paused for a restore",
    })
    await waitFor(() =>
      expect(autopilotMock().dispatches[id]?.length).toBeGreaterThan(0)
    )
    // The ordinary resume is refused while paused for a restore.
    const pause = screen.getByRole("region", { name: "Master pause" })
    expect(within(pause).getByText(/by the system/)).toBeInTheDocument()
    await user.click(
      within(panel).getByRole("button", { name: "Resume after restore" })
    )
    const alert = await within(panel).findByRole("alert")
    expect(alert).toHaveTextContent("Not resumed: 1 send is still outstanding")
    expect(alert).toHaveTextContent(/Email attempt, packet #/)

    // Settle it (reconcile: it did not go out), then the resume goes through.
    const attempt = autopilotMock().dispatches[id].find((d) => d.uncertain)!
    attempt.uncertain = false
    await user.click(
      within(panel).getByRole("button", { name: "Resume after restore" })
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

  it("confirms a submission with a reference", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: /Waiting on you/ }))
    const row = await screen.findByRole("listitem", {
      name: "Did Kariba Freight receive your application?",
    })
    await user.type(
      within(row).getByLabelText(/Reference or what you saw/),
      "KF-7"
    )
    await user.click(
      within(row).getByRole("button", { name: "Yes, it arrived" })
    )
    await waitFor(() =>
      expect(
        applicationsMock().actions.find((a) => a.type === "confirm_submission")!
          .resolution
      ).toEqual({ resolution: "confirmed", reference: "KF-7" })
    )
  })

  it("asks before applying a stage change proposed from the mailbox", async () => {
    const user = userEvent.setup()
    renderApp("/autopilot")
    await user.click(await screen.findByRole("tab", { name: /Waiting on you/ }))
    const row = await screen.findByRole("listitem", {
      name: /sent an interview invitation/,
    })
    expect(within(row).getByText("From your mailbox")).toBeInTheDocument()
    expect(
      within(row).getByText(/suggests moving this to interview/)
    ).toBeInTheDocument()
    const app = applicationsMock().apps.find(
      (a) => a.employer === "Lusaka Fintech Co"
    )!
    expect(app.stage).toBe("submitted")
    await user.click(
      within(row).getByRole("button", { name: "Approve the change" })
    )
    await waitFor(() => expect(app.stage).toBe("interview"))
  })

  it("chooses between two roles by job id", () => {
    expect(
      roleChoices({
        kind: "displace_prepared",
        current: { job_id: "j1", title: "Analyst", score: 80 },
        challenger: { job_id: "j2", title: "Lead", score: 90 },
      }).map((c) => c.job_id)
    ).toEqual(["j1", "j2"])
    expect(
      roleChoices({
        kind: "better_role_after_applying",
        applied_job_id: "j1",
        candidate: { job_id: "j3", title: "Head" },
      }).map((c) => c.job_id)
    ).toEqual(["j1", "j3"])
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
