/**
 * Employers for the mock backend, derived from the Matches jobs and the Applications data the
 * mock already holds (so a chip, a held role and a cooldown agree with the rest of the app).
 * Every employer here is invented. Shapes mirror `EmployerRowOut`, `EmployerDetailOut` and
 * `ChipOut` (CONTRACTS "Wave 4 bulk additions").
 */
import type { ApplicationSummary } from "@/features/applications/api"
import type {
  EmployerChip,
  EmployerDetail,
  EmployerRole,
  EmployerRow,
  EmployerState,
} from "@/features/employers/api"
import type { MockJob } from "./jobs"

const DAY = 86_400_000

export type MockPolicy = {
  cooldown_days: number | null
  always_ask_first: boolean
  never_apply: boolean
  never_reason: string | null
  watched: boolean
  priority: number
  notes: string | null
}

export type EmployerStore = {
  policies: Map<string, MockPolicy>
  /** alias (casefolded) -> canonical name it was merged into */
  aliases: Map<string, string>
  /** employer key -> when the cooldown was ended early */
  endedEarly: Map<string, { at: string; by: string; reason: string }>
  defaultCooldownDays: number
}

export const emptyPolicy = (): MockPolicy => ({
  cooldown_days: null,
  always_ask_first: false,
  never_apply: false,
  never_reason: null,
  watched: false,
  priority: 0,
  notes: null,
})

/** Seed: one employer you never apply to, one you always ask about first. */
export function seedEmployerStore(): EmployerStore {
  return {
    policies: new Map([
      [
        "sahara payments",
        {
          ...emptyPolicy(),
          never_apply: true,
          never_reason: "Conflict of interest",
        },
      ],
      ["tamarind fintech", { ...emptyPolicy(), always_ask_first: true }],
    ]),
    aliases: new Map(),
    endedEarly: new Map(),
    defaultCooldownDays: 30,
  }
}

export const employerKey = (name: string) => name.trim().toLowerCase()

const LIVE = [
  "applying",
  "submitted_unconfirmed",
  "submitted",
  "screening",
  "interview",
  "offer",
]
const ENDED = ["rejected", "withdrawn", "closed", "accepted"]

const day = (iso: string) => iso.slice(0, 10)

export type Source = { jobs: MockJob[]; apps: ApplicationSummary[] }

/** The canonical employer a name resolves to (merges applied). */
const canonical = (s: EmployerStore, name: string) =>
  s.aliases.get(employerKey(name)) ?? name

function appsOf(src: Source, s: EmployerStore, key: string) {
  return src.apps.filter((a) => employerKey(canonical(s, a.employer)) === key)
}

type Cooldown = NonNullable<EmployerDetail["cooldown"]>

function cooldownOf(
  src: Source,
  s: EmployerStore,
  key: string,
  days: number
): Cooldown | null {
  const early = s.endedEarly.get(key)
  let best: {
    app: ApplicationSummary
    start: string
    kind: Cooldown["kind"]
  } | null = null
  for (const a of appsOf(src, s, key)) {
    const ended = ENDED.includes(a.stage)
    const start = ended ? a.updated_at : a.applied_at
    // Only an ended application, or one sent and unanswered, starts a cooldown.
    if (!start || (!ended && a.stage !== "submitted")) continue
    if (early && start <= early.at) continue
    if (!best || start > best.start)
      best = { app: a, start, kind: ended ? "end_state" : "applied_date" }
  }
  if (!best) return null
  const ends = new Date(new Date(best.start).getTime() + days * DAY)
  return {
    kind: best.kind,
    application_id: best.app.id,
    starts_on: day(best.start),
    days,
    ends_on: day(ends.toISOString()),
    running: ends.getTime() > Date.now(),
    rule:
      best.kind === "end_state"
        ? `${days} days after the last application ended (${day(best.start)}), so until ${day(ends.toISOString())}.`
        : `${days} days after you applied (${day(best.start)}) with no reply, so until ${day(ends.toISOString())}.`,
  }
}

function lengthOf(s: EmployerStore, key: string) {
  const p = s.policies.get(key)
  if (p?.cooldown_days != null)
    return { days: p.cooldown_days, source: "this employer's override" }
  if (p?.watched)
    return { days: s.defaultCooldownDays, source: "watched employer default" }
  return {
    days: s.defaultCooldownDays,
    source: "default (matching.employer_cooldown_days)",
  }
}

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso))

function stateOf(
  src: Source,
  s: EmployerStore,
  key: string
): { state: EmployerState; text: string; until: string | null } {
  const p = s.policies.get(key)
  if (p?.never_apply)
    return {
      state: "blocked",
      text: `Never apply: ${p.never_reason ?? "no reason recorded"}`,
      until: null,
    }
  if (appsOf(src, s, key).some((a) => LIVE.includes(a.stage)))
    return { state: "role_in_progress", text: "Role in progress", until: null }
  const cd = cooldownOf(src, s, key, lengthOf(s, key).days)
  if (cd?.running)
    return {
      state: "cooling_down",
      text: `Cooling down until ${shortDate(cd.ends_on)}`,
      until: cd.ends_on,
    }
  if (p?.always_ask_first)
    return { state: "always_ask_first", text: "Always ask first", until: null }
  return { state: "free", text: "Free to apply", until: null }
}

export function chipFor(
  src: Source,
  s: EmployerStore,
  employer: string,
  jobId?: string
): EmployerChip {
  const key = employerKey(canonical(s, employer))
  const { state, text } = stateOf(src, s, key)
  const live = appsOf(src, s, key).filter((a) => LIVE.includes(a.stage))
  return {
    state,
    text,
    live: live.length,
    live_elsewhere: live.filter((a) => a.job_id !== jobId).length,
  }
}

function rowFor(
  src: Source,
  s: EmployerStore,
  key: string,
  name: string
): EmployerRow {
  const st = stateOf(src, s, key)
  const apps = appsOf(src, s, key)
  const p = s.policies.get(key) ?? emptyPolicy()
  const jobs = src.jobs.filter(
    (j) => employerKey(canonical(s, j.canonical_employer)) === key
  )
  const applied = apps
    .map((a) => a.applied_at)
    .filter((x): x is string => !!x)
    .sort()
  return {
    key,
    name,
    state: st.state,
    state_text: st.text,
    applications: apps.length,
    live: apps.filter((a) => LIVE.includes(a.stage)).length,
    last_applied_at: applied.at(-1) ?? null,
    roles_seen: jobs.length,
    held_roles: jobs.filter((j) => j.conflict_state === "held").length,
    cooldown_until: st.until,
    always_ask_first: p.always_ask_first,
    never_apply: p.never_apply,
    never_reason: p.never_reason,
    watched: p.watched,
    priority: p.priority,
    cooldown_days: p.cooldown_days,
  }
}

export function listEmployers(
  src: Source,
  s: EmployerStore,
  filter: { state?: string | null; q?: string | null }
): EmployerRow[] {
  const names = new Map<string, string>()
  for (const j of src.jobs) {
    const n = canonical(s, j.canonical_employer)
    names.set(employerKey(n), n)
  }
  for (const a of src.apps) {
    const n = canonical(s, a.employer)
    names.set(employerKey(n), n)
  }
  const q = filter.q?.trim().toLowerCase()
  return [...names]
    .map(([key, name]) => rowFor(src, s, key, name))
    .filter(
      (r) =>
        (!filter.state || r.state === filter.state) &&
        (!q || r.name.toLowerCase().includes(q))
    )
    .sort((a, b) => b.priority - a.priority || a.name.localeCompare(b.name))
}

const roleOf = (j: MockJob, apps: ApplicationSummary[]): EmployerRole => {
  const app = apps.find((a) => a.job_id === j.id)
  return {
    job_id: j.id,
    title: j.title,
    triage: j.triage,
    conflict_state: j.conflict_state,
    conflict_note: j.conflict?.note ?? null,
    score: j.best_score,
    application_id: app?.id ?? null,
    stage: app?.stage ?? null,
    posted_at: j.posted_at,
  }
}

export function employerDetail(
  src: Source,
  s: EmployerStore,
  key: string
): EmployerDetail | null {
  const row = listEmployers(src, s, {}).find((r) => r.key === key)
  if (!row) return null
  const apps = appsOf(src, s, key)
  const jobs = src.jobs.filter(
    (j) => employerKey(canonical(s, j.canonical_employer)) === key
  )
  const roles = jobs.map((j) => roleOf(j, apps))
  const group = roles.filter(
    (r) => r.conflict_state === "winner" || r.conflict_state === "held"
  )
  const len = lengthOf(s, key)
  const early = s.endedEarly.get(key)
  const cd = cooldownOf(src, s, key, len.days)
  return {
    employer: row,
    cooldown: cd,
    cooldown_days: len.days,
    cooldown_days_source: len.source,
    cooldown_ended_early_at: early?.at ?? null,
    cooldown_ended_early_by: early?.by ?? null,
    cooldown_ended_early_reason: early?.reason ?? null,
    roles,
    conflict_groups: group.some((r) => r.conflict_state === "held")
      ? [group]
      : [],
    history: apps.map((a) => ({
      application_id: a.id,
      job_id: a.job_id,
      title: a.title,
      stage: a.stage,
      applied_at: a.applied_at,
      ended_at: ENDED.includes(a.stage) ? a.updated_at : null,
      counts_toward_cooldown: cd?.application_id === a.id,
    })),
    contacts: [],
    aliases: [...s.aliases]
      .filter(([, v]) => employerKey(v) === key)
      .map(([k]) => k),
    notes: s.policies.get(key)?.notes ?? null,
  }
}
