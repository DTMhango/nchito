/**
 * In-memory mock backend state for MSW (dev with VITE_MOCK=1, and tests).
 * All people and organisations here are fictional.
 *
 * In the browser the state is kept in localStorage so a reload keeps you signed in.
 * URL switches for demos and screenshots:
 *   ?mock=fresh      no owner yet (first-run setup)
 *   ?mock=signed-out owner exists, no session
 *   ?mock=signed-in  owner exists and is signed in
 */
import {
  DEFAULT_APPEARANCE,
  type Appearance,
  type Theme,
} from "@/themes/schema"
import type { AutopilotState, OwnerCreate } from "@/lib/api/types"

export type MockDb = {
  owner: (OwnerCreate & { totp_secret: string | null }) | null
  session: boolean
  appearance: Appearance
  customThemes: Theme[]
  /** Theme studio: revisions per owner theme, the current one, and the default theme id. */
  themeRevisions: Record<string, MockThemeRevision[]>
  themeCurrent: Record<string, number>
  defaultThemeId: string
  autopilot: AutopilotState
  captured: { id: string; url?: string | null; text?: string | null }[]
}

export type MockThemeRevision = {
  number: number
  parent: number | null
  note: string
  actor: string
  created_at: string
  body: Omit<Theme, "id" | "builtin">
}

export const DEMO_OWNER: OwnerCreate = {
  email: "owner@example.com",
  password: "demo-password",
  display_name: "Chanda",
  timezone: "Africa/Lusaka",
}

const KEY = "nchito.mock.db"

function seed(
  kind: "fresh" | "signed-out" | "signed-in" = "signed-out"
): MockDb {
  return {
    owner: kind === "fresh" ? null : { ...DEMO_OWNER, totp_secret: null },
    session: kind === "signed-in",
    appearance: { ...DEFAULT_APPEARANCE },
    customThemes: [],
    themeRevisions: {},
    themeCurrent: {},
    defaultThemeId: DEFAULT_APPEARANCE.theme_id,
    autopilot: {
      paused: false,
      paused_at: null,
      paused_by: null,
      reason: null,
      summary: { cancelled: [], paused: [], already_out: [] },
    },
    captured: [],
  }
}

let state: MockDb = seed()

function persist() {
  if (typeof window === "undefined" || import.meta.env.MODE === "test") return
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    /* ignore */
  }
}

/** Load browser state, honouring the ?mock= switch. */
export function loadBrowserDb() {
  const url = new URL(window.location.href)
  const kind = url.searchParams.get("mock")
  if (kind === "fresh" || kind === "signed-out" || kind === "signed-in") {
    state = seed(kind)
    url.searchParams.delete("mock")
    window.history.replaceState(null, "", url.toString())
    persist()
    return
  }
  try {
    const raw = window.localStorage.getItem(KEY)
    if (raw) state = { ...seed(), ...(JSON.parse(raw) as Partial<MockDb>) }
  } catch {
    /* corrupt: start over */
  }
}

export const db = {
  get: () => state,
  update(fn: (s: MockDb) => void) {
    fn(state)
    persist()
  },
  reset(kind: "fresh" | "signed-out" | "signed-in" = "signed-out") {
    state = seed(kind)
  },
}
