/**
 * Refusals from the apply layer (CONTRACTS, wave 2 send-flow): every 409/422 on packet build,
 * prepare, approve, reject, request changes, dispatch, cancel, reconcile, handoff and
 * mark-submitted is `{detail: {code, reason, ...}}`, and `DispatchCreateOut.code` /
 * `ApprovalStatusOut.code` carry the same codes on a 200 that did not go ahead. Screens switch
 * on `code`, never on the wording; `reason` is shown as secondary detail.
 */
import type { Schemas } from "./types"
import { isApiError } from "./client"

type GateResult = Schemas["GateResult"]

/** What a screen can offer next. Each screen renders the ones it can act on. */
export type RefusalAction =
  | "recheck"
  | "confirm_address"
  | "edit_address"
  | "reload"
  | "prepare_again"
  | "open_studio"
  | "open_answers"
  | "connect_mailbox"
  | "resume_autopilot"
  | "reconcile"

type Entry = { text: string; action?: RefusalAction }

/** Plain words per code (`app/apply/errors.py::CODES`). Unknown codes read as `refused`. */
export const REFUSAL_TEXT: Record<string, Entry> = {
  no_spec: {
    text: "There is no tailored draft yet. Tailor the application first.",
    action: "open_studio",
  },
  check_stale: {
    text: "The checks are out of date. Re-run the checks, then send again.",
    action: "recheck",
  },
  check_blocking: {
    text: "A check blocks sending. Fix what it flags, or waive it once, then send again.",
    action: "recheck",
  },
  document_not_rendered: {
    text: "The documents do not come from the checked draft. Re-run the checks, then send again.",
    action: "recheck",
  },
  answers_waiting: {
    text: "A form question still needs your answer.",
    action: "open_answers",
  },
  no_destination: {
    text: "There is nowhere to apply: the posting gives no link and no address. Add the application address on the job page.",
    action: "edit_address",
  },
  no_identity: {
    text: "There is no address to send from. Connect a mailbox in Settings, or add your email to your account.",
    action: "connect_mailbox",
  },
  unknown_template: {
    text: "That template no longer exists. Pick another one and try again.",
  },
  invalid_packet: {
    text: "The packet is not complete. Prepare it again.",
    action: "prepare_again",
  },
  no_packet: {
    text: "No packet has been prepared yet.",
    action: "prepare_again",
  },
  packet_superseded: {
    text: "A newer version of this packet exists. Review that one instead.",
    action: "reload",
  },
  packet_changed: {
    text: "Something in the packet changed after it was built. Prepare it again.",
    action: "prepare_again",
  },
  channel_mismatch: {
    text: "The approval was for a different way of applying. Review it again.",
    action: "reload",
  },
  illegal_stage: {
    text: "This application has already moved on, so its packet can no longer change.",
  },
  not_approved: { text: "Nothing approved is waiting to be sent." },
  mode_not_allowed: {
    text: "This campaign's automation does not let the system send it. Apply yourself, or change the campaign.",
  },
  excluded: { text: "Your campaign rules exclude this role." },
  held_by_conflict: {
    text: "Another role at this employer goes ahead first, so this one is held.",
  },
  employer_cooldown: {
    text: "You applied to this employer recently. It waits until the cool-down ends.",
  },
  paused: {
    text: "Automatic sending is paused. Nothing goes out until you resume it.",
    action: "resume_autopilot",
  },
  quiet_hours: {
    text: "It is quiet hours. It goes out when they end.",
  },
  cap_reached: { text: "The sending cap for today or this week is reached." },
  budget: { text: "The AI budget is used up." },
  duplicate: { text: "This was already sent. It is never sent twice." },
  permit_outstanding: {
    text: "Another send for this application is still in progress.",
  },
  posting_changed: {
    text: "The posting changed after the packet was built. Prepare it again.",
    action: "prepare_again",
  },
  role_closed: {
    text: "The role may be closed: it has not been confirmed open recently.",
  },
  deadline_passed: { text: "The closing date has passed." },
  email_unconfirmed: {
    text: "The application address is not confirmed. Confirm it before anything is emailed to it.",
    action: "confirm_address",
  },
  destination_unverified: {
    text: "The application link has not been checked yet.",
  },
  untrusted_site: {
    text: "The application site is not on your trusted list.",
  },
  answers_not_automatic: {
    text: "Some answers need your approval before they can go automatically.",
  },
  runner_refused: { text: "The browser runner refused this send." },
  channel_unavailable: {
    text: "That way of applying is not available for this role.",
  },
  retry_limit: { text: "It has been tried as many times as allowed." },
  waiver_reason_required: { text: "Give a reason for the waiver." },
  note_required: { text: "Say what should change." },
  not_found: { text: "It no longer exists." },
  already_handed_over: {
    text: "It has already been handed over, so it can no longer be cancelled.",
    action: "reload",
  },
  already_settled: {
    text: "This send has already been settled.",
    action: "reload",
  },
  not_uncertain: {
    text: "This send is not uncertain, so there is nothing to reconcile.",
    action: "reload",
  },
  not_started: { text: "This send has not started yet." },
  still_queued: {
    text: "It is still waiting to be sent. Cancel it first if you want to apply yourself.",
  },
  nothing_to_submit: { text: "There is nothing to record as submitted." },
  system_channel: {
    text: "The system sends this one, so there is nothing for you to submit.",
  },
  invalid_address: { text: "That is not an email address." },
  no_address: {
    text: "There is no address to confirm. Enter one first.",
    action: "edit_address",
  },
  below_auto_threshold: {
    text: "The score is below your auto-apply line, so it needs your approval.",
  },
  unknown_data: {
    text: "Something your rules depend on is unknown, so it needs your approval.",
  },
  pay_not_stated: {
    text: "The posting does not state the pay, so it needs your approval.",
  },
  always_ask_first: { text: "Your rules say to ask you first." },
  campaign_unconfirmed: {
    text: "The campaign is not confirmed yet, so nothing is sent automatically.",
  },
  refused: { text: "It was refused." },
}

/** A structured refusal read from an error body (`{detail: {code, reason, ...}}`). */
export type Refusal = {
  code: string | null
  reason: string
  gates: GateResult[]
  outstanding: string[]
}

/** Read a refusal from an error; null when it is not a structured refusal. */
export function refusalOf(e: unknown): Refusal | null {
  if (!isApiError(e)) return null
  const d = (e.body as { detail?: unknown } | undefined)?.detail
  if (!d || typeof d !== "object" || Array.isArray(d)) return null
  const o = d as Record<string, unknown>
  return {
    code: typeof o.code === "string" ? o.code : null,
    reason: typeof o.reason === "string" ? o.reason : e.message,
    gates: Array.isArray(o.gates) ? (o.gates as GateResult[]) : [],
    outstanding: Array.isArray(o.outstanding)
      ? o.outstanding.filter((x): x is string => typeof x === "string")
      : [],
  }
}

/** A refusal in plain words: the text, what to offer, and the server's reason as detail. */
export type Explained = {
  code: string
  text: string
  action: RefusalAction | null
  /** The server's own words, shown smaller; null when they add nothing. */
  reason: string | null
  gates: GateResult[]
}

/** Plain words for a code (and the server's reason) from a 200 that did not go ahead. */
export function explainCode(
  code: string | null | undefined,
  reason?: string | null,
  gates: GateResult[] = []
): Explained {
  const detail = reason?.trim() || null
  // A code this list does not know (another area's refusal): its own words are the text.
  if (code && !(code in REFUSAL_TEXT) && detail)
    return { code, text: detail, action: null, reason: null, gates }
  const key = code && code in REFUSAL_TEXT ? code : "refused"
  const entry = REFUSAL_TEXT[key]
  return {
    code: key,
    text: entry.text,
    action: entry.action ?? null,
    reason: detail && detail !== entry.text ? detail : null,
    gates,
  }
}

/** Plain words for any error from the apply layer; a non-refusal keeps its own message. */
export function explainError(e: unknown, fallback: string): Explained {
  const r = refusalOf(e)
  if (r?.code) return explainCode(r.code, r.reason, r.gates)
  const message = r?.reason ?? (e instanceof Error ? e.message : "")
  return {
    code: "error",
    text: message || fallback,
    action: null,
    reason: null,
    gates: r?.gates ?? [],
  }
}
