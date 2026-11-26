/**
 * What the set-up guide remembers in this browser: how you started, which criteria you chose to
 * "decide later", which optional steps you skipped. Progress itself is read from the server
 * (what actually exists), so a different browser still shows the right ticks.
 *
 * "Decide later" is only ever a note to the screen. Nothing is written for that criterion, so
 * the campaign stays unconfirmed and automation stays off (unknown is not yes).
 */
import { useCallback, useState } from "react"

export const CRITERIA = [
  "pay_floor",
  "countries",
  "seniority",
  "work_rights",
  "relocation",
] as const
export type CriterionKey = (typeof CRITERIA)[number]

export type StartKind = "empty" | "kit_file" | "template" | "old_kit"

export type Local = {
  start: StartKind | null
  /** Set when an old-kit import was committed: its items carry the "may be stale" mark. */
  oldKit: boolean
  decideLater: CriterionKey[]
  skipped: number[]
  /** Answer-bank rows this guide created for work rights and relocation, so a re-save updates them. */
  answerIds: Partial<Record<CriterionKey, string>>
  campaignId: string | null
}

const KEY = "nchito.onboarding"
const EMPTY: Local = {
  start: null,
  oldKit: false,
  decideLater: [],
  skipped: [],
  answerIds: {},
  campaignId: null,
}

function load(): Local {
  try {
    const raw = window.localStorage.getItem(KEY)
    return raw ? { ...EMPTY, ...(JSON.parse(raw) as Partial<Local>) } : EMPTY
  } catch {
    return EMPTY
  }
}

export const clearOnboardingLocal = () => {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    /* storage can be blocked; the guide still works without it */
  }
}

export function useLocalOnboarding() {
  const [local, setLocal] = useState<Local>(load)
  const update = useCallback((patch: Partial<Local>) => {
    setLocal((cur) => {
      const next = { ...cur, ...patch }
      try {
        window.localStorage.setItem(KEY, JSON.stringify(next))
      } catch {
        /* see above */
      }
      return next
    })
  }, [])
  return [local, update] as const
}
