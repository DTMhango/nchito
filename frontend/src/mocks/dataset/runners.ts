/**
 * Fictional gateway tokens, runners, runner tasks and portal accounts for the Runners and
 * Accounts screens. Every name, address and secret is invented (example domains only).
 */
import type { RunnerStatus, Token } from "@/features/settings/runners/api"
import type {
  PortalAccount,
  RunnerCaps,
  RunnerTask,
} from "@/features/accounts/w3-pending-types"

const HOUR = 3_600_000
const ago = (hours: number) => new Date(Date.now() - hours * HOUR).toISOString()
export const uuid = (kind: string, n: number) =>
  `${kind}0000000-0000-4000-8000-${String(n).padStart(12, "0")}`

export const PC_ID = uuid("c", 1)
export const SERVER_ID = uuid("c", 2)
export const PAUSED_ID = uuid("c", 3)

const token = (n: number, over: Partial<Token>): Token => ({
  id: uuid("c", n),
  created_at: ago(24 * 30),
  updated_at: ago(24 * 30),
  name: "Token",
  prefix: `nch_${n}a9f2`,
  scopes: ["gateway:tasks", "gateway:packets", "gateway:permits"],
  runner_kind: "pc",
  last_used_at: null,
  revoked_at: null,
  suspended_at: null,
  suspended_reason: null,
  ...over,
})

export type MockRunners = {
  tokens: Token[]
  statuses: RunnerStatus[]
  caps: Record<string, RunnerCaps>
  /** Tasks per token. A blocked task names the pending action that holds it. */
  tasks: Record<string, (RunnerTask & { blocked_by?: string })[]>
  accounts: PortalAccount[]
}

export function seedRunners(): MockRunners {
  return {
    tokens: [
      token(1, {
        name: "Office PC",
        last_used_at: ago(0.2),
        scopes: [
          "gateway:tasks",
          "gateway:packets",
          "gateway:permits",
          "gateway:sweep",
        ],
      }),
      token(2, {
        name: "Home server",
        runner_kind: "server",
        last_used_at: ago(2),
        scopes: ["gateway:tasks", "gateway:packets", "gateway:permits"],
      }),
      token(3, {
        name: "Old laptop",
        last_used_at: ago(6),
        suspended_at: ago(5),
        suspended_reason:
          "A submission to a Lever form was reported without a granted permit.",
      }),
      token(4, {
        name: "Test token",
        revoked_at: ago(24 * 5),
        last_used_at: ago(24 * 6),
      }),
    ],
    statuses: [
      {
        token_id: PC_ID,
        name: "Office PC",
        runner_kind: "pc",
        last_seen_at: ago(0.01),
        online: true,
        current_task_id: null,
      },
      {
        token_id: SERVER_ID,
        name: "Home server",
        runner_kind: "server",
        last_seen_at: ago(2),
        online: false,
        current_task_id: null,
      },
      {
        token_id: PAUSED_ID,
        name: "Old laptop",
        runner_kind: "pc",
        last_seen_at: ago(5),
        online: false,
        current_task_id: null,
      },
    ],
    caps: {
      [PC_ID]: {
        max_tasks_per_day: 20,
        max_steps_per_task: 60,
        cost_ceiling_per_task: null,
      },
      [SERVER_ID]: {
        max_tasks_per_day: 10,
        max_steps_per_task: 40,
        cost_ceiling_per_task: 0.5,
      },
      [PAUSED_ID]: {
        max_tasks_per_day: null,
        max_steps_per_task: null,
        cost_ceiling_per_task: null,
      },
    },
    tasks: { [PC_ID]: [], [SERVER_ID]: [], [PAUSED_ID]: [] },
    accounts: [
      {
        id: uuid("a", 1),
        portal_name: "Zambezi Mining careers",
        portal_url: "https://careers.zambezi-mining.example/login",
        status: "none",
        signed_in_runner: null,
        email_used: null,
        last_sign_in_at: null,
        applications_waiting: 2,
      },
      {
        id: uuid("a", 2),
        portal_name: "Kafue Analytics careers",
        portal_url: "https://kafue-analytics.example/careers",
        status: "signed_in",
        signed_in_runner: "Office PC",
        email_used: "chanda@example.com",
        last_sign_in_at: ago(30),
        applications_waiting: 0,
      },
      {
        id: uuid("a", 3),
        portal_name: "Arch Reinsurance careers",
        portal_url: "https://arch-re.example/jobs",
        status: "created",
        signed_in_runner: null,
        email_used: "chanda@example.com",
        last_sign_in_at: null,
        applications_waiting: 1,
      },
    ],
  }
}
