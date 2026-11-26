import { describe, expect, it } from "vitest"
import { ApiError } from "./client"
import { REFUSAL_TEXT, explainCode, explainError, refusalOf } from "./refusals"

const coded = (code: string, reason: string, extra = {}) =>
  new ApiError(409, { detail: { code, reason, ...extra } })

describe("refusals", () => {
  it("has plain words for every code the apply layer raises", () => {
    // app/apply/errors.py::CODES
    const codes = [
      "no_spec",
      "check_stale",
      "check_blocking",
      "document_not_rendered",
      "answers_waiting",
      "no_destination",
      "no_identity",
      "unknown_template",
      "invalid_packet",
      "no_packet",
      "packet_superseded",
      "packet_changed",
      "channel_mismatch",
      "illegal_stage",
      "not_approved",
      "mode_not_allowed",
      "excluded",
      "held_by_conflict",
      "employer_cooldown",
      "paused",
      "quiet_hours",
      "cap_reached",
      "budget",
      "duplicate",
      "permit_outstanding",
      "posting_changed",
      "role_closed",
      "deadline_passed",
      "email_unconfirmed",
      "destination_unverified",
      "untrusted_site",
      "answers_not_automatic",
      "runner_refused",
      "channel_unavailable",
      "retry_limit",
      "waiver_reason_required",
      "note_required",
      "not_found",
      "already_handed_over",
      "already_settled",
      "not_uncertain",
      "not_started",
      "still_queued",
      "nothing_to_submit",
      "system_channel",
      "invalid_address",
      "no_address",
      "below_auto_threshold",
      "unknown_data",
      "pay_not_stated",
      "always_ask_first",
      "campaign_unconfirmed",
      "refused",
    ]
    for (const c of codes) expect(REFUSAL_TEXT[c]?.text, c).toBeTruthy()
  })

  it("offers the next step for the codes that have one", () => {
    expect(explainCode("check_stale").action).toBe("recheck")
    expect(explainCode("email_unconfirmed").action).toBe("confirm_address")
    expect(explainCode("packet_superseded").action).toBe("reload")
    expect(explainCode("paused").text).toMatch(/paused/)
    expect(explainCode("quiet_hours").text).toMatch(/quiet hours/)
  })

  it("keeps the server's reason as secondary detail, and drops it when it repeats the text", () => {
    const x = explainError(coded("duplicate", "attempt 3 already sent"), "x")
    expect(x.text).toBe(REFUSAL_TEXT.duplicate.text)
    expect(x.reason).toBe("attempt 3 already sent")
    expect(explainCode("duplicate", REFUSAL_TEXT.duplicate.text).reason).toBe(
      null
    )
  })

  it("reads an unlisted code as its own words, and no code as refused", () => {
    expect(explainCode("restore_paused", "paused for a restore").text).toBe(
      "paused for a restore"
    )
    expect(explainCode(null).code).toBe("refused")
  })

  it("carries the gates of a refused approval", () => {
    const gate = { gate: "role_open", outcome: "unknown" }
    const r = refusalOf(
      coded("role_closed", "role_open: unknown", { gates: [gate] })
    )
    expect(r?.gates).toEqual([gate])
    expect(
      explainError(coded("role_closed", "x", { gates: [gate] }), "").gates
    ).toHaveLength(1)
  })

  it("falls back to the error's own message for anything that is not a refusal", () => {
    expect(explainError(new Error("Network down"), "fallback").text).toBe(
      "Network down"
    )
    expect(explainError(null, "fallback").text).toBe("fallback")
    // a coded body still reads as the reason in a plain message
    expect(coded("paused", "automatic sending is paused").message).toBe(
      "automatic sending is paused"
    )
  })
})
