/**
 * Fictional packets, gates, dispatch attempts, runners and trusted sites for the Autopilot
 * mock backend. Every employer, address and person is invented (example domains only).
 */
import type {
  ApplicationSummary,
  DispatchOut,
  GateResult,
  ManualHandoffOut,
  PacketOut,
  PendingAction,
  TimelineEvent,
  ReceiptOut,
  RunnerStatus,
  TrustedSiteOut,
} from "@/features/autopilot/api"

const DAY = 86_400_000
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString()

const HASH_A = "a3f9c21e5b7d4086".repeat(4)
const HASH_B = "71be0d94c2a85f3e".repeat(4)
const HASH_C = "0c4e8a17d9b36f52".repeat(4)
const SHA = (n: number) => String(n).repeat(64).slice(0, 64)

const uuid = (kind: string, n: number) =>
  `${kind}0000000-0000-4000-8000-${String(n).padStart(12, "0")}`

export type MockAutopilot = {
  packets: Record<string, PacketOut[]>
  dispatches: Record<string, DispatchOut[]>
  trusted: TrustedSiteOut[]
  runners: RunnerStatus[]
  /** When set, approve answers 409 with this code and reason, and the open gates. */
  refuseApproval: { code: string; reason: string } | null
  /** Reject and request-changes calls, in order (tests read them). */
  decisions: { id: string; kind: "reject" | "changes"; text: string | null }[]
}

type Pair = [employer: string, build: (app: ApplicationSummary) => PacketOut[]]

function packet(
  app: ApplicationSummary,
  version: number,
  hash: string,
  over: Partial<PacketOut> = {},
  contents: Partial<PacketOut["contents"]> = {}
): PacketOut {
  const email = app.channel === "email"
  return {
    id: uuid("b", version + Number(app.id.slice(-3)) * 10),
    created_at: ago(3 - version),
    updated_at: ago(3 - version),
    application_id: app.id,
    version,
    content_hash: hash,
    approved_at: null,
    approved_by: null,
    invalidated_at: null,
    invalidated_reason: null,
    contents: {
      requisition: `REQ-${4800 + Number(app.id.slice(-3))}`,
      destination: email
        ? {
            url: "mailto:recruiting@kafue-analytics.example",
            domain: "kafue-analytics.example",
            verified: true,
            trusted: true,
          }
        : {
            url: `https://careers.${slug(app.employer)}.example/apply/4821`,
            domain: `careers.${slug(app.employer)}.example`,
            verified: true,
            trusted: false,
          },
      sending_identity: "Chanda <owner@example.com>",
      answers: [
        {
          question: "Do you have the right to work in Zambia?",
          value: "Yes",
          answer_id: "ans-1",
          material: true,
        },
        {
          question: "Notice period",
          value: "1 month",
          answer_id: "ans-2",
          material: false,
        },
      ],
      email: email
        ? {
            to: ["recruiting@kafue-analytics.example"],
            cc: [],
            subject: `Application: ${app.title}`,
            body: "Dear hiring team,\n\nPlease find my application attached.\n\nKind regards,\nChanda",
          }
        : null,
      files: [
        {
          name: "CV - Chanda.pdf",
          kind: "cv",
          sha256: SHA(1),
          document_id: null,
          share_link: null,
        },
        {
          name: "Letter.pdf",
          kind: "letter",
          sha256: SHA(2),
          document_id: null,
          share_link: null,
        },
      ],
      link_permissions: [],
      channel: app.channel ?? null,
      job_version: null,
      ...contents,
    },
    ...over,
  }
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-")

export const PACKET_BUILDERS: Pair[] = [
  [
    // Approved once, then an answer changed: the earlier approval no longer applies.
    "Zambezi Mining Systems",
    (app) => [
      packet(app, 1, HASH_A, {
        approved_at: ago(2),
        approved_by: "owner",
        invalidated_at: ago(1),
        invalidated_reason:
          "Answer changed: Notice period, 1 month to 3 months.",
      }),
      packet(
        app,
        2,
        HASH_B,
        {},
        {
          answers: [
            {
              question: "Do you have the right to work in Zambia?",
              value: "Yes",
              answer_id: "ans-1",
              material: true,
            },
            {
              question: "Notice period",
              value: "3 months",
              answer_id: "ans-2",
              material: false,
            },
          ],
        }
      ),
    ],
  ],
]

export function packetsFor(
  app: ApplicationSummary,
  store: MockAutopilot
): PacketOut[] {
  const have = store.packets[app.id]
  if (have) return have
  const seeded = PACKET_BUILDERS.find(([e]) => e === app.employer)
  const made = seeded ? seeded[1](app) : [packet(app, 1, HASH_C)]
  store.packets[app.id] = made
  return made
}

/** Gate results for a packet. The Zambezi packet has one failed and one unknown gate. */
export function gatesFor(app: ApplicationSummary): GateResult[] {
  const pass = (gate: string, detail?: string): GateResult => ({
    gate,
    passed: true,
    detail: detail ?? null,
    outcome: "pass",
  })
  if (app.employer === "Zambezi Mining Systems")
    return [
      pass("score_threshold", "Score 86, threshold 85."),
      pass("mandatory_filters"),
      pass("document_checks"),
      {
        gate: "role_open",
        passed: false,
        detail: "The posting has not been rechecked in 3 days.",
        outcome: "unknown",
      },
      {
        gate: "always_ask",
        passed: false,
        detail:
          "careers.zambezi-mining.example is not a trusted site yet, so the agent must ask first.",
        outcome: "fail",
      },
      pass("daily_cap", "2 of 5 used today."),
      pass("conflict_winner", "Highest score among roles at this employer."),
    ]
  return [
    pass("score_threshold"),
    pass("mandatory_filters"),
    pass("document_checks"),
    pass("role_open"),
    pass("daily_cap"),
  ]
}

export function receiptFor(
  app: ApplicationSummary,
  packets: PacketOut[]
): ReceiptOut {
  const current = [...packets].sort((a, b) => b.version - a.version)[0]
  const changes =
    app.employer === "Zambezi Mining Systems"
      ? [
          {
            path: "answers.Notice period",
            before: "1 month",
            after: "3 months",
            material: true,
          },
        ]
      : []
  return {
    application_id: app.id,
    packet: current,
    employer: app.employer,
    destination: current.contents.destination.domain,
    role: app.title,
    pay_answers: ["Expected pay: ZMW 62,000 a month"],
    work_rights_answers: ["Right to work in Zambia: Yes"],
    attachments: current.contents.files.map((f) => f.name),
    unusual_disclosures:
      app.employer === "Zambezi Mining Systems"
        ? ["Your referee list is included"]
        : [],
    changes_since_last_look: changes,
    action_label:
      app.channel === "email"
        ? "Send email to recruiter"
        : app.channel === "manual"
          ? "Prepare for you to send"
          : "Let the agent submit",
    gates: gatesFor(app),
  }
}

export function handoffFor(app: ApplicationSummary): ManualHandoffOut {
  return {
    posting_url: `https://careers.${slug(app.employer)}.example/jobs/${app.id.slice(-4)}`,
    files: [
      `/api/applications/${app.id}/documents/cv`,
      `/api/applications/${app.id}/documents/letter`,
    ],
    answers: [
      { question: "Full name", answer: "Chanda Mwila" },
      { question: "Right to work in Zambia", answer: "Yes" },
      { question: "Notice period", answer: "1 month" },
    ],
    remaining_steps: [
      "Open the posting and choose Apply.",
      "Upload the CV and the letter.",
      "Paste the answers in the order shown.",
      "Submit, then record it here with the confirmation.",
    ],
  }
}

export function seedAutopilot(): MockAutopilot {
  return {
    packets: {},
    dispatches: {},
    refuseApproval: null,
    decisions: [],
    trusted: [
      trusted(
        1,
        "boards.greenhouse.io",
        "Greenhouse",
        "Known application system"
      ),
      trusted(2, "jobs.lever.co", "Lever", "Known application system"),
      trusted(3, "kafue-analytics.example", null, "Direct employer site"),
    ],
    runners: [
      {
        token_id: uuid("c", 1),
        name: "Office PC",
        runner_kind: "pc",
        last_seen_at: ago(0.01),
        online: true,
        current_task_id: null,
      },
      {
        token_id: uuid("c", 2),
        name: "Home server",
        runner_kind: "server",
        last_seen_at: ago(2),
        online: false,
        current_task_id: null,
      },
    ],
  }
}

function trusted(
  n: number,
  domain: string,
  system: string | null,
  note: string
): TrustedSiteOut {
  return {
    id: uuid("d", n),
    created_at: ago(30 - n),
    updated_at: ago(30 - n),
    domain,
    system,
    note,
    trusted_by: "owner",
  }
}

/** Dispatch attempts by employer, so they follow the application ids of the shared dataset. */
export function dispatchesFor(app: ApplicationSummary): DispatchOut[] {
  const base = (n: number, over: Partial<DispatchOut>): DispatchOut => ({
    id: uuid("e", n + Number(app.id.slice(-3)) * 10),
    created_at: ago(1),
    updated_at: ago(1),
    application_id: app.id,
    packet_hash: HASH_A,
    channel: app.channel ?? "email",
    status: "reserved",
    send_after: null,
    provider_message_id: null,
    outcome_at: null,
    gate_results: [],
    error: null,
    started_at: null,
    evidence: null,
    uncertain: false,
    reconcile_attempts: 0,
    last_reconciled_at: null,
    deferred_reason: null,
    deferred_until: null,
    ...over,
  })
  switch (app.employer) {
    case "Kariba Freight":
      return [
        base(1, {
          status: "bounced",
          error: "The address recruiting@old.example does not exist.",
          created_at: ago(2),
          outcome_at: ago(2),
        }),
        base(2, {
          status: "unknown",
          outcome_at: null,
          started_at: ago(1),
          uncertain: true,
          reconcile_attempts: 2,
          last_reconciled_at: ago(0.5),
        }),
      ]
    case "Lusaka Fintech Co":
      return [
        base(1, {
          status: "acknowledged",
          provider_message_id: "<msg-4821@mail.example.com>",
          evidence: {
            kind: "sent_mail_id",
            value: "<msg-4821@mail.example.com>",
            screenshot_ref: null,
            at: ago(3),
          },
          outcome_at: ago(3),
        }),
      ]
    case "Nyika Labs":
      return [
        base(1, { status: "handed_off", channel: "browser" }),
        // Due inside quiet hours: postponed to their end (`deferred_reason`, and timeline `dispatch_deferred`).
        base(2, {
          status: "reserved",
          channel: "email",
          send_after: new Date(Date.now() + 9 * 3_600_000).toISOString(),
          deferred_reason: "quiet_hours",
          deferred_until: new Date(Date.now() + 9 * 3_600_000).toISOString(),
        }),
      ]
    default:
      return []
  }
}

/** Timeline entries the dispatch layer writes: a quiet-hours postponement for each deferred send. */
export function dispatchEvents(
  app: ApplicationSummary,
  dispatches: DispatchOut[]
): TimelineEvent[] {
  if (app.employer !== "Nyika Labs") return []
  return dispatches
    .filter((d) => d.status === "reserved" && d.send_after)
    .map((d) => ({
      id: uuid("f", Number(d.id.slice(-4))),
      created_at: ago(0.01),
      kind: "dispatch_deferred",
      actor: "system",
      detail: {
        attempt_id: d.id,
        reason: "quiet hours",
        send_after: d.send_after,
      },
    }))
}

/** A stage change proposed from the mailbox: a pending action to approve, never applied silently. */
export function mailProposalFor(app: ApplicationSummary): PendingAction {
  return {
    id: uuid("a", 900),
    created_at: ago(0.1),
    updated_at: ago(0.1),
    type: "follow_up",
    application_id: app.id,
    agent_task_id: null,
    group_key: null,
    title: `${app.employer} sent an interview invitation: move to interview?`,
    detail: {
      kind: "mail_stage_proposal",
      category: "interview",
      thread_id: uuid("a", 901),
      message_id: "<invite-77@mail.example.com>",
      proposed_stage: "interview",
      subject: "Interview: next steps",
    },
    checkpoint: null,
    deadline: null,
    status: "open",
    snoozed_until: null,
    snoozed: false,
    employer: app.employer,
    job_title: app.title,
    resolution: null,
  }
}
