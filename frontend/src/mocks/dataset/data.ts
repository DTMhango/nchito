/**
 * Fictional data for the Data, Connections and onboarding mocks. Invented people only
 * (example.com addresses).
 */
import type { components } from "@/lib/api/types"

type S = components["schemas"]

export type DiffRow = S["ImportDiffItem"] & { group?: string }

const answer = (key: string, group: string, after: string): DiffRow => ({
  entity: "answer",
  key,
  change: "add",
  before: null,
  after,
  group,
})

/** What an old job-hunting folder would bring in: every item protected or decisive comes first. */
export const OLD_KIT_DIFF: DiffRow[] = [
  answer("Pay floor, permanent", "pay_floors", "ZMW 480,000 a year"),
  answer("Countries I will work in", "countries", "Zambia, Kenya, remote"),
  answer("Seniority", "seniority", "Head of, Director"),
  answer("Right to work", "visa", "Zambian citizen"),
  answer("Open to relocation", "relocation", "Yes, within Africa"),
  answer("Notice period", "notice", "One month"),
  {
    entity: "guardrail",
    key: "Never mention the previous employer",
    change: "add",
    before: null,
    after: "never_mention",
    group: "guardrail",
  },
  {
    entity: "answer",
    key: "Salary expectation",
    change: "conflict",
    before: "ZMW 500,000",
    after: "ZMW 450,000",
    group: "salary",
  },
  {
    entity: "fact",
    key: "F-100",
    change: "unchanged",
    before: "Led month-end close",
    after: "Led month-end close",
  },
]

export const KIT_FILE_DIFF: DiffRow[] = [
  {
    entity: "template",
    key: "Plain CV",
    change: "add",
    before: null,
    after: "classic",
  },
  {
    entity: "rubric",
    key: "Finance leadership",
    change: "update",
    before: "version 2",
    after: "version 3",
  },
]

export const DEMO_BACKUPS: S["BackupOut"][] = [
  {
    id: "bk-3",
    created_at: "2026-11-26T02:00:00Z",
    size_bytes: 18_400_000,
    target: "local",
    encrypted: true,
  },
  {
    id: "bk-2",
    created_at: "2026-11-25T02:00:00Z",
    size_bytes: 18_100_000,
    target: "local",
    encrypted: true,
  },
]

export const SHARE_HITS: S["PersonalDetailHit"][] = [
  {
    path: "templates/cover-letter.md",
    kind: "email",
    excerpt: "chanda@example.com",
  },
]

/** `GET /api/health/detail`: one part not yet known, which the screen must not call OK. */
export const DEMO_HEALTH: S["DetailedHealth"] = {
  status: "degraded",
  version: "0.2.0",
  time: "2026-11-26T09:00:00Z",
  components: [
    {
      name: "database",
      status: "ok",
      detail: "Answers in 2 ms.",
      at: null,
      value: 2,
    },
    {
      name: "worker",
      status: "ok",
      detail: "Heartbeat 20 s ago.",
      at: null,
      value: 20,
    },
    { name: "sweep", status: "unknown", detail: null, at: null, value: null },
    {
      name: "backup",
      status: "ok",
      detail: "Last backup 7 h ago.",
      at: "2026-11-26T02:00:00Z",
      value: 7,
    },
    {
      name: "disk",
      status: "warn",
      detail: "900 MB free.",
      at: null,
      value: 900,
    },
    {
      name: "connections",
      status: "ok",
      detail: "1 connection working.",
      at: null,
      value: 1,
    },
  ],
  queue: { waiting: 3, running: 1, failed: 0 },
  connections: [
    {
      id: "conn-mail",
      provider: "imap_smtp",
      label: "Search mailbox",
      enabled: true,
      health: "ok",
      last_checked_at: "2026-11-26T08:30:00Z",
    },
  ],
  workers: [
    {
      ok: true,
      last_beat_at: "2026-11-26T08:59:40Z",
      age_seconds: 20,
      workers: 1,
    },
  ],
}
