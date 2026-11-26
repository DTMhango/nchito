/**
 * Mock backend for messages, follow-ups and the wind-down (wave 4). Mirrors the real shapes; the
 * checks are faked: a body mentioning "salary" blocks as an unconfirmed commitment.
 */
import { http, HttpResponse } from "msw"
import type { components } from "@/lib/api/types"
import { applicationsMock } from "./applications"

type S = components["schemas"]
type Message = S["MessageOut"]
type WindDown = S["WindDownOut"]
type Item = S["WindDownItemOut"]

type State = {
  messages: Message[]
  windDown: WindDown
  dueStatus: Record<string, S["FollowupItemOut"]["status"]>
}

let state: State
const SENT_TO = "jobs@kafue-analytics.example"

const now = () => new Date().toISOString()
const refused = (code: string, reason: string, status = 409) =>
  HttpResponse.json({ detail: { code, reason } }, { status })

function checksFor(body: string, to: string[], known: string[]) {
  const results: S["CheckResult"][] = []
  const questions: string[] = []
  if (/salary/i.test(body)) {
    results.push({
      check: "commitment",
      status: "block",
      detail:
        "letter[1]: mentions pay and you have no confirmed answer: decide what to say, or take it out",
      guardrail_id: null,
      waived: false,
    })
    questions.push("Pay: What are your salary expectations?")
  }
  for (const a of to)
    if (!known.includes(a))
      results.push({
        check: "recipients",
        status: "block",
        detail: `${a} is not an address this application has used: confirm it`,
        guardrail_id: null,
        waived: false,
      })
  if (!results.length)
    results.push({
      check: "fact_trace",
      status: "pass",
      detail: null,
      guardrail_id: null,
      waived: false,
    })
  return { results, questions }
}

function withChecks(m: Message): Message {
  const known = [...m.known_recipients, ...m.confirmed_recipients]
  const { results, questions } = checksFor(m.body, m.to, known)
  return {
    ...m,
    check_results: results,
    questions,
    check_status: results.some((r) => r.status === "block") ? "block" : "pass",
    unconfirmed_recipients: m.to.filter((a) => !known.includes(a)),
    checked: true,
    paragraphs: m.body.split("\n\n").map((text) => ({ text, fact_ids: [] })),
  }
}

export function seedMessage(
  appId: string,
  over: Partial<Message> = {}
): Message {
  const m = withChecks({
    id: crypto.randomUUID(),
    created_at: now(),
    updated_at: now(),
    application_id: appId,
    kind: "follow_up",
    status: "draft",
    send_state: "none",
    automatic: false,
    thread_id: null,
    thread_ref: null,
    to: [SENT_TO],
    cc: [],
    known_recipients: [SENT_TO],
    confirmed_recipients: [],
    unconfirmed_recipients: [],
    subject: "Re: Application: Data Analyst",
    body: "Dear hiring team,\n\nIs there any news on my application?\n\nKind regards,",
    paragraphs: [],
    questions: [],
    check_results: [],
    checked: true,
    check_status: "pass",
    note: null,
    slot: null,
    excerpt: null,
    sequence: 1,
    origin: "generated",
    model: "fake",
    cost_micros: 0,
    error: null,
    created_by: "owner",
    packet: null,
    dispatch: null,
    ...over,
  })
  state.messages.push(m)
  return m
}

function windDownView(): WindDown {
  const apps = applicationsMock().apps.filter((a) =>
    ["submitted", "screening", "interview", "offer"].includes(a.stage)
  )
  const groups: Record<string, Item[]> = {}
  for (const a of apps)
    (groups[a.stage] ??= []).push({
      key: `application:${a.id}`,
      kind: "application",
      label: `${a.title} at ${a.employer}`,
      detail: `stage ${a.stage}`,
      choices: ["keep", "pause", "withdraw"],
      choice: null,
      effect: null,
      application_id: a.id,
    })
  return {
    ...state.windDown,
    live_applications: groups,
    campaigns: [
      {
        key: "campaign:c-1",
        kind: "campaign",
        label: "Analytics roles",
        detail: "active; 1 of 1 schedule(s) on",
        choices: ["keep", "pause"],
        choice: null,
        effect: null,
        application_id: null,
      },
    ],
  }
}

export const resetFollowupsMock = () => {
  state = {
    messages: [],
    dueStatus: {},
    windDown: {
      status: "none",
      id: null,
      reason: null,
      started_at: null,
      started_by: null,
      reopened_at: null,
      autopilot_paused: false,
      queued_sends: [],
      approved_unsent: [],
      live_applications: {},
      interviews: [],
      pending_actions: [],
      campaigns: [],
    },
  }
}
resetFollowupsMock()

export const followupsMock = () => state

const EFFECT: Record<string, string> = {
  keep: "nothing changes",
  pause: "paused until the search is reopened",
  withdraw:
    "withdraw email drafted for your approval (never sent automatically)",
}

const findMsg = (id: unknown) => state.messages.find((m) => m.id === String(id))
const replace = (m: Message) => {
  state.messages = state.messages.map((x) => (x.id === m.id ? m : x))
  return HttpResponse.json(m)
}

export const followupsHandlers = [
  http.get("*/api/applications/:id/messages", ({ params }) => {
    const id = String(params.id)
    return HttpResponse.json({
      application_id: id,
      thread: {
        thread_id: null,
        subject: "Application: Data Analyst",
        sender: null,
        last_message_at: null,
        employer_replied: false,
        sent_to: [SENT_TO],
        sending_identity: "owner@example.com",
      },
      messages: state.messages.filter((m) => m.application_id === id),
    })
  }),
  http.post("*/api/applications/:id/messages", async ({ params, request }) => {
    const body = (await request.json()) as S["MessageCreateIn"]
    const m = seedMessage(String(params.id), {
      kind: body.kind,
      note: body.note ?? null,
      slot: body.slot ?? null,
      sequence: null,
    })
    return HttpResponse.json(m, { status: 201 })
  }),
  http.put("*/api/messages/:id", async ({ params, request }) => {
    const m = findMsg(params.id)
    if (!m) return refused("not_found", "message not found", 404)
    const body = (await request.json()) as S["MessageEditIn"]
    const to = body.to ?? m.to
    const confirmed = body.confirm_recipients
      ? [
          ...new Set([
            ...m.confirmed_recipients,
            ...to.filter((a) => !m.known_recipients.includes(a)),
          ]),
        ]
      : m.confirmed_recipients
    return replace(
      withChecks({
        ...m,
        to,
        body: body.body ?? m.body,
        subject: body.subject ?? m.subject,
        confirmed_recipients: confirmed,
        status: "draft",
        automatic: false,
        origin: "owner",
      })
    )
  }),
  http.post("*/api/messages/:id/approve", ({ params }) => {
    const m = findMsg(params.id)
    if (!m) return refused("not_found", "message not found", 404)
    if (m.check_status === "block")
      return refused(
        m.questions.length ? "message_questions" : "check_blocking",
        "the checks block this message"
      )
    return replace({
      ...m,
      status: "approved",
      packet: {
        id: crypto.randomUUID(),
        version: 2,
        content_hash: "f".repeat(64),
        approved_at: now(),
        approved_by: "owner",
        invalidated_at: null,
      },
    })
  }),
  http.post("*/api/messages/:id/send", ({ params }) => {
    const m = findMsg(params.id)
    if (!m) return refused("not_found", "message not found", 404)
    if (m.status !== "approved")
      return HttpResponse.json({
        status: "denied",
        reason: "the message is not approved",
        code: "not_approved",
        gates: [],
        message: m,
      })
    const sent: Message = { ...m, send_state: "queued" }
    state.messages = state.messages.map((x) => (x.id === m.id ? sent : x))
    return HttpResponse.json({
      status: "queued",
      reason: "queued: it goes after the send delay",
      code: null,
      gates: [],
      message: sent,
    })
  }),
  http.post("*/api/messages/:id/:action", ({ params }) => {
    const m = findMsg(params.id)
    if (!m) return refused("not_found", "message not found", 404)
    switch (params.action) {
      case "cancel":
        return replace({ ...m, send_state: "cancelled" })
      case "discard":
        return replace({ ...m, status: "discarded" })
      default:
        return replace(m)
    }
  }),
  http.get("*/api/follow-ups", () => {
    const apps = applicationsMock().apps.filter((a) => a.stage === "submitted")
    return HttpResponse.json({
      auto_send: false,
      items: apps
        .filter((a) => state.dueStatus[a.id] !== "not_needed")
        .map((a, i) => ({
          id: null,
          application_id: a.id,
          job_id: a.job_id,
          title: a.title,
          employer: a.employer,
          stage: a.stage,
          sequence: 1,
          due_at: new Date(Date.now() + (i - 1) * 86_400_000).toISOString(),
          status: state.dueStatus[a.id] ?? (i === 0 ? "due" : "upcoming"),
          message_id: null,
          message_state: null,
        })),
    })
  }),
  http.post("*/api/follow-ups/:id/draft", ({ params }) => {
    state.dueStatus[String(params.id)] = "drafted"
    return HttpResponse.json(seedMessage(String(params.id)), { status: 201 })
  }),
  http.post("*/api/follow-ups/:id/:action", ({ params }) => {
    const id = String(params.id)
    state.dueStatus[id] = params.action === "snooze" ? "snoozed" : "not_needed"
    const a = applicationsMock().apps.find((x) => x.id === id)!
    return HttpResponse.json({
      id: crypto.randomUUID(),
      application_id: id,
      job_id: a.job_id,
      title: a.title,
      employer: a.employer,
      stage: a.stage,
      sequence: 1,
      due_at: now(),
      status: state.dueStatus[id],
      message_id: null,
      message_state: null,
    })
  }),
  http.get("*/api/wind-down", () => HttpResponse.json(state.windDown)),
  http.post("*/api/wind-down", async ({ request }) => {
    const body = (await request.json()) as S["WindDownStartIn"]
    state.windDown = {
      ...state.windDown,
      status: "active",
      id: crypto.randomUUID(),
      reason: `Accepted an offer: wind-down${body.reason ? ` (${body.reason})` : ""}`,
      started_at: now(),
      started_by: "owner",
      autopilot_paused: true,
    }
    state.windDown = windDownView()
    return HttpResponse.json(state.windDown)
  }),
  http.post("*/api/wind-down/choices", async ({ request }) => {
    const { key, choice } = (await request.json()) as S["WindDownChoiceIn"]
    if (state.windDown.status !== "active")
      return refused("no_winddown", "no wind-down is active")
    const mark = (items: Item[]) =>
      items.map((i) =>
        i.key === key ? { ...i, choice, effect: EFFECT[choice] } : i
      )
    const wd = state.windDown
    state.windDown = {
      ...wd,
      campaigns: mark(wd.campaigns),
      live_applications: Object.fromEntries(
        Object.entries(wd.live_applications).map(([k, v]) => [k, mark(v)])
      ),
    }
    return HttpResponse.json(state.windDown)
  }),
  http.post("*/api/wind-down/reopen", () => {
    state.windDown = {
      ...state.windDown,
      status: "reopened",
      reopened_at: now(),
    }
    return HttpResponse.json(state.windDown)
  }),
]
