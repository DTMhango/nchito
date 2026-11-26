/**
 * Pure rules for the Autopilot screens: how a gate reads, when an approval still applies,
 * what a dispatch attempt means and how limits are validated. Kept apart from the
 * components so the safety wording is tested on its own.
 */
import type {
  AutomationMode,
  Channel,
  DispatchOut,
  GateResult,
  PacketOut,
  PendingAction,
  ResolveIn,
  SettingOut,
} from "./api"

// ---- gates (DESIGN 8.1, 18.4) ----

export type GateState = "pass" | "fail" | "unknown"

/**
 * The gate's tri-state comes from `outcome` alone. Only `pass` passes; `fail` fails; `unknown`,
 * null, missing or anything else is unknown (unknown is not yes). `passed` is never read.
 */
export function gateState(
  g: Partial<GateResult> | null | undefined
): GateState {
  if (g?.outcome === "pass") return "pass"
  if (g?.outcome === "fail") return "fail"
  return "unknown"
}

export const GATE_STATE_TEXT: Record<GateState, string> = {
  pass: "Passed",
  fail: "Failed",
  unknown: "Unknown",
}

const GATE_NAMES: Record<string, string> = {
  score_threshold: "Score at or above the auto-apply threshold",
  mandatory_filters: "Mandatory filters",
  document_checks: "Document checks",
  answers_auto: "Every question answered from approved answers",
  role_open: "Role confirmed open recently",
  prior_application: "No earlier application to this requisition",
  conflict_winner: "Winner among roles at this employer",
  employer_cooldown: "Employer cool-down",
  always_ask: "Employer not set to always ask first",
  channel_permitted: "Channel permitted for this source",
  daily_cap: "Daily cap",
  weekly_cap: "Weekly cap",
  quiet_hours: "Outside quiet hours",
  budget: "Budget available",
  global_pause: "Automatic sending not paused",
  destination: "Destination checked",
}

export const gateName = (gate: string) =>
  GATE_NAMES[gate] ??
  gate.replace(/[_.]/g, " ").replace(/^\w/, (c) => c.toUpperCase())

export type AutoVerdict = {
  /** True only when there is at least one gate and every gate is a clear pass. */
  canAuto: boolean
  blocking: { gate: GateResult; state: Exclude<GateState, "pass"> }[]
  headline: string
}

/** "Why can or can't this go automatically": built from the gates the server returned. */
export function autoVerdict(gates: readonly GateResult[]): AutoVerdict {
  const blocking = gates
    .map((gate) => ({ gate, state: gateState(gate) }))
    .filter(
      (x): x is { gate: GateResult; state: "fail" | "unknown" } =>
        x.state !== "pass"
    )
  if (gates.length === 0)
    return {
      canAuto: false,
      blocking,
      headline:
        "Not checked yet, so it cannot go automatically. It needs your approval.",
    }
  if (blocking.length === 0)
    return {
      canAuto: true,
      headline: "Every check passed. It may go automatically.",
      blocking,
    }
  const n = blocking.length
  return {
    canAuto: false,
    blocking,
    headline: `${n} check${n === 1 ? "" : "s"} did not pass, so it needs your approval and will not go automatically.`,
  }
}

// ---- packet and approval (DESIGN 18.2) ----

/** First eight hex characters: enough to compare by eye, never a substitute for the full hash. */
export const shortHash = (hash: string) => `#${hash.slice(0, 8)}`

export type ApprovalStanding =
  | { kind: "approved"; packet: PacketOut }
  | { kind: "invalidated"; earlier: PacketOut; reason: string }
  | { kind: "none" }

/**
 * Does an approval cover the current packet? The latest version is the one that counts. An
 * earlier version that was approved and later invalidated, with the latest not approved,
 * means "the earlier approval no longer applies".
 */
export function approvalStanding(
  packets: readonly PacketOut[]
): ApprovalStanding {
  if (packets.length === 0) return { kind: "none" }
  const sorted = [...packets].sort((a, b) => b.version - a.version)
  const current = sorted[0]
  if (current.approved_at && !current.invalidated_at)
    return { kind: "approved", packet: current }
  const earlier = sorted.find((p) => p.approved_at && p.invalidated_at)
  if (earlier)
    return {
      kind: "invalidated",
      earlier,
      reason:
        earlier.invalidated_reason ??
        "An item in the packet changed after you approved it.",
    }
  return { kind: "none" }
}

// ---- channels (DESIGN 18.1) ----

export const CHANNEL_LABEL: Record<Channel, string> = {
  email: "Email",
  browser: "Browser agent",
  manual: "Manual handoff",
}

export type Enforcement = "server" | "audited" | "owner"

export const ENFORCEMENT: Record<
  Enforcement,
  { label: string; tone: "good" | "warn" | "neutral" }
> = {
  server: { label: "Enforced by the server", tone: "good" },
  audited: { label: "Instructed and audited", tone: "warn" },
  owner: { label: "You decide", tone: "neutral" },
}

export const CHANNEL_RULES: {
  channel: Channel
  title: string
  enforcement: Enforcement
  body: string
}[] = [
  {
    channel: "email",
    title: "Email",
    enforcement: "server",
    body: "The server is the sender, so nothing leaves without every check passing. Messages wait in the outbox for the send delay and you can cancel them until then.",
  },
  {
    channel: "browser",
    title: "Browser agent on a trusted site",
    enforcement: "audited",
    body: "The agent is told to ask for a permit before it submits and normally does, but the server cannot physically stop a click on the employer's site. Every release and submission is audited, and a submission without a permit suspends that runner.",
  },
  {
    channel: "browser",
    title: "Browser agent on an unknown site",
    enforcement: "audited",
    body: "Same as above, and it asks you first until you trust the site (see Trusted sites).",
  },
  {
    channel: "manual",
    title: "Manual handoff",
    enforcement: "owner",
    body: "Nchito prepares the documents and answers; you open the posting and submit it yourself, then record it.",
  },
]

// ---- dispatch (DESIGN 8.5, 18.3) ----

export type DispatchKind =
  | "queued"
  | "postponed"
  | "handed_off"
  | "sent"
  | "uncertain"
  | "failed"
  | "cancelled"

export type DispatchView = {
  kind: DispatchKind
  label: string
  tone: "good" | "warn" | "danger" | "info" | "neutral"
  explain: string
  /** The proof that it left, when there is any. */
  evidence: string | null
}

const EVIDENCE_LABEL: Record<
  NonNullable<DispatchOut["evidence"]>["kind"],
  string
> = {
  confirmation_page: "Confirmation page",
  reference: "Reference",
  sent_mail_id: "Sent mail ID",
  confirmation_email: "Confirmation email",
  owner_marked: "Recorded by you",
}

/** The recorded proof, in words: the evidence the server holds, else the provider message id. */
export function evidenceText(
  d: Pick<DispatchOut, "evidence" | "provider_message_id">
): string | null {
  if (d.evidence?.value) return d.evidence.value
  return d.provider_message_id ?? null
}

export const evidenceLabel = (d: Pick<DispatchOut, "evidence">) =>
  d.evidence ? EVIDENCE_LABEL[d.evidence.kind] : "Proof"

export const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })

/** A time in the owner's zone: "07:00" today, else "Fri 07:00". */
export function clockIn(iso: string, timeZone?: string, now = new Date()) {
  const opts = { timeZone } as const
  try {
    const time = new Intl.DateTimeFormat("en-GB", {
      ...opts,
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso))
    const day = (d: Date) =>
      new Intl.DateTimeFormat("en-GB", { ...opts, dateStyle: "short" }).format(
        d
      )
    if (day(new Date(iso)) === day(now)) return time
    const weekday = new Intl.DateTimeFormat("en-GB", {
      ...opts,
      weekday: "short",
    }).format(new Date(iso))
    return `${weekday} ${time}`
  } catch {
    return stamp(iso)
  }
}

/**
 * "Held for quiet hours until 07:00": a reserved send the server postponed at send time
 * (`deferred_reason`, `deferred_until`). Null for any other attempt.
 */
export function deferredText(
  d: Partial<Pick<DispatchOut, "deferred_reason" | "deferred_until">> &
    Pick<DispatchOut, "status">,
  timeZone?: string,
  now = new Date()
): string | null {
  if (d.status !== "reserved" || d.deferred_reason !== "quiet_hours")
    return null
  return d.deferred_until
    ? `Held for quiet hours until ${clockIn(d.deferred_until, timeZone, now)}`
    : "Held for quiet hours"
}

type DispatchFacts = Pick<
  DispatchOut,
  "status" | "provider_message_id" | "error" | "send_after"
> &
  Partial<
    Pick<
      DispatchOut,
      "evidence" | "uncertain" | "deferred_reason" | "deferred_until"
    >
  >

/**
 * What an attempt means to the owner. "Sent" needs evidence. An attempt the server marks
 * uncertain (or `unknown`) is never retried; the owner reconciles it. A send postponed by quiet
 * hours is waiting, not failed.
 */
export function dispatchView(
  d: DispatchFacts,
  timeZone?: string
): DispatchView {
  const held = deferredText(d, timeZone)
  const evidence = evidenceText({
    evidence: d.evidence ?? null,
    provider_message_id: d.provider_message_id,
  })
  if (d.uncertain && d.status !== "cancelled")
    return uncertain(
      "We cannot tell whether this left. It stays locked as submitted-unconfirmed and is never sent again automatically, so you cannot send it twice."
    )
  switch (d.status) {
    case "reserved":
      if (held)
        return {
          kind: "postponed",
          label: "Quiet hours",
          tone: "info",
          explain: `${held}. It goes out then; you can cancel it until it is sent.`,
          evidence: null,
        }
      return {
        kind: "queued",
        label: "Queued",
        tone: "info",
        explain: d.send_after
          ? `Waiting in the outbox until ${stamp(d.send_after)}. You can cancel it until it is sent.`
          : "Reserved and about to go. You can cancel it until it is sent.",
        evidence: null,
      }
    case "handed_off":
      return {
        kind: "handed_off",
        label: "With the agent",
        tone: "info",
        explain:
          "Given to the browser agent. It is not counted as sent until the agent reports proof.",
        evidence: null,
      }
    case "sent":
    case "acknowledged":
      return evidence
        ? {
            kind: "sent",
            label:
              d.status === "acknowledged" ? "Acknowledged" : "Sent with proof",
            tone: "good",
            explain:
              d.status === "acknowledged"
                ? "The employer acknowledged it."
                : "It left, and the proof is recorded.",
            evidence,
          }
        : {
            kind: "sent",
            label: "Sent, no proof recorded",
            tone: "warn",
            explain: "It was recorded as sent, but no proof was kept with it.",
            evidence: null,
          }
    case "unknown":
      return uncertain(
        "We cannot tell whether this left. It stays locked as submitted-unconfirmed and is never sent again automatically, so you cannot send it twice."
      )
    case "bounced":
      return {
        kind: "failed",
        label: "Bounced",
        tone: "danger",
        explain: d.error ?? "The recipient's mail server rejected it.",
        evidence: null,
      }
    case "failed":
      return {
        kind: "failed",
        label: "Failed",
        tone: "danger",
        explain: d.error ?? "It did not go out.",
        evidence: null,
      }
    case "cancelled":
      return {
        kind: "cancelled",
        label: "Cancelled",
        tone: "neutral",
        explain: "It was cancelled before it was sent.",
        evidence: null,
      }
  }
}

function uncertain(explain: string): DispatchView {
  return {
    kind: "uncertain",
    label: "Uncertain",
    tone: "warn",
    explain,
    evidence: null,
  }
}

/** Only a waiting attempt can be cancelled. Nothing can be retried, least of all an uncertain one. */
export const canCancel = (v: DispatchView) =>
  v.kind === "queued" || v.kind === "postponed"

// ---- limits (DESIGN 8.1, settings registry) ----

export type LimitKey =
  | "scoring.threshold_shortlist"
  | "scoring.threshold_tailor"
  | "scoring.threshold_auto_apply"
  | "automation.daily_cap"
  | "automation.weekly_cap"
  | "matching.max_live_per_employer"
  | "matching.employer_cooldown_days"
  | "automation.quiet_hours_start"
  | "automation.quiet_hours_end"

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/

/**
 * Validate one limit against the registry bounds and the rules between limits (daily at most
 * weekly; shortlist at most tailor at most auto-apply). `values` holds the other current values.
 */
export function validateLimit(
  setting: Pick<SettingOut, "key" | "kind" | "label"> &
    Partial<Pick<SettingOut, "minimum" | "maximum">>,
  raw: string,
  values: Record<string, unknown>
): { ok: true; value: number | string } | { ok: false; message: string } {
  if (setting.kind === "time") {
    return TIME.test(raw.trim())
      ? { ok: true, value: raw.trim() }
      : { ok: false, message: "Use a 24-hour time such as 21:00." }
  }
  if (raw.trim() === "" || !/^-?\d+$/.test(raw.trim()))
    return { ok: false, message: "Enter a whole number." }
  const n = Number(raw)
  if (setting.minimum != null && n < setting.minimum)
    return { ok: false, message: `Must be at least ${setting.minimum}.` }
  if (setting.maximum != null && n > setting.maximum)
    return { ok: false, message: `Must be at most ${setting.maximum}.` }
  const num = (k: string) => Number(values[k])
  const k = setting.key
  if (k === "automation.daily_cap" && n > num("automation.weekly_cap"))
    return {
      ok: false,
      message: `The daily cap can't be above the weekly cap (${num("automation.weekly_cap")}).`,
    }
  if (k === "automation.weekly_cap" && n < num("automation.daily_cap"))
    return {
      ok: false,
      message: `The weekly cap can't be below the daily cap (${num("automation.daily_cap")}).`,
    }
  if (
    k === "scoring.threshold_shortlist" &&
    n > num("scoring.threshold_tailor")
  )
    return {
      ok: false,
      message: "The shortlist line can't be above the tailor line.",
    }
  if (
    k === "scoring.threshold_tailor" &&
    (n < num("scoring.threshold_shortlist") ||
      n > num("scoring.threshold_auto_apply"))
  )
    return {
      ok: false,
      message: "The tailor line must sit between shortlist and auto-apply.",
    }
  if (
    k === "scoring.threshold_auto_apply" &&
    n < num("scoring.threshold_tailor")
  )
    return {
      ok: false,
      message: "The auto-apply line can't be below the tailor line.",
    }
  return { ok: true, value: n }
}

/** Where an effective value comes from, in words (the registry default, or the owner). */
export function sourceOf(
  s: Pick<SettingOut, "is_default" | "updated_by" | "updated_at" | "version">
): string {
  if (s.is_default) return "Default"
  const who = s.updated_by === "owner" || !s.updated_by ? "you" : s.updated_by
  const when = s.updated_at
    ? ` on ${new Date(s.updated_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
    : ""
  return `Set by ${who}${when}`
}

export const MODE_LABEL: Record<AutomationMode, string> = {
  save_only: "Save only",
  prepare: "Prepare documents",
  ask_then_apply: "Ask me, then apply",
  auto_apply: "Apply automatically",
}

// ---- pending actions (DESIGN 8.4, 18.4) ----

export type ChoiceKind =
  | "continue"
  | "answer"
  | "confirm"
  | "submitted"
  | "choose"
  | "review"
  | "proposal"
  /** A link to `/accounts/handoff/$id`, where the blocker's own choices are. */
  | "handoff"
  /** A link to the job's Changes tab (`kind` posting_changed / posting_closed). */
  | "changes"
  | "none"

export type PendingKindInfo = {
  label: string
  /** One plain sentence on what the system is waiting for. */
  waiting: string
  kind: ChoiceKind
  primary: string
  resolution?: ResolveIn["resolution"]
}

export const PENDING_KINDS: Record<PendingAction["type"], PendingKindInfo> = {
  approve: {
    label: "Approval",
    waiting: "A packet is ready. Nothing is sent until you approve it.",
    kind: "review",
    primary: "Review and approve",
  },
  sign_in: {
    label: "Sign in",
    waiting: "The agent needs you to sign in to a portal.",
    kind: "continue",
    primary: "I've signed in, continue",
    resolution: "continue",
  },
  create_account: {
    label: "New account",
    waiting: "The portal wants an account. Creating one is your decision.",
    kind: "continue",
    primary: "I've created it, continue",
    resolution: "continue",
  },
  captcha: {
    label: "CAPTCHA",
    waiting: "The agent hit a CAPTCHA only you can solve.",
    kind: "continue",
    primary: "I've solved it, continue",
    resolution: "continue",
  },
  unknown_question: {
    label: "New question",
    waiting: "A form asked something your answer bank cannot answer.",
    kind: "answer",
    primary: "Save answer",
    resolution: "answered",
  },
  assessment: {
    label: "Assessment",
    waiting: "The employer wants a test or assessment done by you.",
    kind: "handoff",
    primary: "Choose what to do",
  },
  declaration: {
    label: "Declaration",
    waiting:
      "A declaration needs your own answer. It is never filled in for you.",
    kind: "handoff",
    primary: "Choose what to do",
  },
  unsupported_form: {
    label: "Form it cannot use",
    waiting:
      "The form is one the agent cannot fill in. Apply yourself, or skip the role.",
    kind: "handoff",
    primary: "Apply myself or skip",
  },
  redirect_off_domain: {
    label: "Left the site",
    waiting:
      "The form sent the runner off the employer's site, so it stopped. Any unused submit permit was withdrawn.",
    kind: "confirm",
    primary: "I've looked at it, close it",
    resolution: "dismissed",
  },
  page_instruction: {
    label: "Page asked for more",
    waiting:
      "The page asked for something outside the application, so the runner stopped. It never acts on what a page asks.",
    kind: "confirm",
    primary: "I've looked at it, close it",
    resolution: "dismissed",
  },
  confirm_submission: {
    label: "Confirm it arrived",
    waiting:
      "We could not confirm this left. Check your sent mail or the portal, then tell us.",
    kind: "submitted",
    primary: "Yes, it arrived",
    resolution: "confirmed",
  },
  review_import: {
    label: "Review import",
    waiting: "Imported data needs a look before it counts.",
    kind: "confirm",
    primary: "Looks right",
    resolution: "dismissed",
  },
  conflict_choice: {
    label: "Choose a role",
    waiting:
      "Two roles at one employer compete. Choose which one to go ahead with.",
    kind: "choose",
    primary: "Go with this one",
    resolution: "chosen",
  },
  answer_review_due: {
    label: "Answer review",
    waiting: "A saved answer is due for a check.",
    kind: "confirm",
    primary: "Still correct",
    resolution: "dismissed",
  },
  follow_up: {
    label: "Follow up",
    waiting: "No reply yet. A nudge may help.",
    kind: "confirm",
    primary: "Done",
    resolution: "dismissed",
  },
}

const STAGE_WORDS: Record<string, string> = {
  submitted: "submitted",
  interview: "interview",
  rejected: "rejected",
  info_requested: "information requested",
  offer: "offer",
}

/**
 * The kind info for one action. A stage change proposed from the mailbox
 * (`detail.kind == "mail_stage_proposal"`) is approved, never applied silently.
 */
export function pendingInfo(action: Pick<PendingAction, "type" | "detail">) {
  const d = action.detail as Record<string, unknown>
  if (d.kind === "mail_stage_proposal") {
    const stage =
      typeof d.proposed_stage === "string"
        ? (STAGE_WORDS[d.proposed_stage] ?? d.proposed_stage.replace(/_/g, " "))
        : null
    return {
      label: "From your mailbox",
      waiting: stage
        ? `A message in your mailbox suggests moving this to ${stage}. Nothing changes until you approve.`
        : "A message in your mailbox suggests a change. Nothing changes until you approve.",
      kind: "proposal",
      primary: "Approve the change",
      resolution: "approved",
    } satisfies PendingKindInfo
  }
  if (d.kind === "posting_changed" || d.kind === "posting_closed")
    return {
      label: d.kind === "posting_closed" ? "Posting closed" : "Posting changed",
      waiting:
        d.kind === "posting_closed"
          ? "The posting was taken down after you applied. See what was recorded."
          : "The posting changed after you applied. See what changed.",
      kind: "changes",
      primary:
        d.kind === "posting_closed" ? "See the closure" : "See what changed",
    } satisfies PendingKindInfo
  if (action.type === "sign_in" && d.kind === "verification_code")
    return {
      label: "Verification code",
      waiting:
        "The portal sent a verification code. Enter it in the runner's browser.",
      kind: "continue",
      primary: "I entered the code, continue",
      resolution: "continue",
    } satisfies PendingKindInfo
  return PENDING_KINDS[action.type]
}

export type RoleChoice = { job_id: string; label: string }

const asObj = (v: unknown) =>
  v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null

function choice(o: Record<string, unknown> | null, note: string): RoleChoice[] {
  if (!o || typeof o.job_id !== "string") return []
  const label = [
    typeof o.title === "string" ? o.title : null,
    o.score != null ? `score ${String(o.score)}` : null,
    note,
  ]
    .filter(Boolean)
    .join(", ")
  return [{ job_id: o.job_id, label }]
}

/**
 * The two roles of a "choose a role" action, read defensively from the untyped `detail`:
 * `displace_prepared` (current vs challenger) or `better_role_after_applying` (applied vs
 * candidate). Answered with `chosen_job_id`.
 */
export function roleChoices(detail: Record<string, unknown>): RoleChoice[] {
  if (detail.kind === "better_role_after_applying") {
    const applied =
      typeof detail.applied_job_id === "string"
        ? [
            {
              job_id: detail.applied_job_id,
              label: [
                "The role you already applied for",
                detail.applied_score != null
                  ? `score ${String(detail.applied_score)}`
                  : null,
              ]
                .filter(Boolean)
                .join(", "),
            },
          ]
        : []
    return [...applied, ...choice(asObj(detail.candidate), "the newer role")]
  }
  return [
    ...choice(asObj(detail.current), "the one being prepared"),
    ...choice(asObj(detail.challenger), "the new contender"),
  ]
}

export const answerOptions = (detail: Record<string, unknown>): string[] =>
  Array.isArray(detail.options)
    ? detail.options.filter((o): o is string => typeof o === "string")
    : []

/** A normalised, lower-case domain from whatever the owner typed or pasted. */
export function normaliseDomain(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/^[a-z]+:\/\//, "")
    .replace(/^www\./, "")
    .replace(/[/?#].*$/, "")
}

export const DOMAIN_PATTERN = /^[a-z0-9.-]+\.[a-z]{2,}$/
