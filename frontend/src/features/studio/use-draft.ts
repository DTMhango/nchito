import { useCallback, useMemo, useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useAutosave } from "@/features/campaigns/use-autosave"
import {
  runChecks,
  saveSpec,
  studioKeys,
  type ApplicationDetail,
  type CheckResult,
} from "./api"
import { fingerprint, toDraft, toSpec, type Draft } from "./draft"

/** Where this browser remembers which version was last checked (a per-viewer convenience). */
const checkedKey = (id: string) => `nchito.studio.checked.${id}`
const readChecked = (id: string): string | null => {
  try {
    return localStorage.getItem(checkedKey(id))
  } catch {
    return null
  }
}
const writeChecked = (id: string, print: string) => {
  try {
    localStorage.setItem(checkedKey(id), print)
  } catch {
    // Without storage the stale marker simply resets on reload.
  }
}

export type CheckState = "current" | "stale" | "unchecked"

/**
 * The editable draft of one application's spec: autosaved after a pause, with the check
 * results and whether they still describe what is on screen ("edited since last check").
 */
export function useDraft(app: ApplicationDetail) {
  const qc = useQueryClient()
  const [draft, setDraftState] = useState<Draft>(() => toDraft(app.spec))
  const current = useRef(draft)
  const [results, setResults] = useState<CheckResult[]>(app.check_results)
  const [checkedPrint, setCheckedPrint] = useState<string | null>(
    () =>
      readChecked(app.id) ??
      (app.check_results.length > 0 ? fingerprint(app.spec) : null)
  )

  const save = useCallback(
    async (d: Draft) => {
      const out = await saveSpec(app.id, toSpec(d))
      qc.setQueryData(studioKeys.application(app.id), out)
      void qc.invalidateQueries({ queryKey: ["applications"] })
    },
    [app.id, qc]
  )
  const autosave = useAutosave(save, 900)
  const { touch } = autosave

  const setDraft = useCallback(
    (update: (d: Draft) => Draft) => {
      const next = update(current.current)
      current.current = next
      setDraftState(next)
      touch(next)
    },
    [touch]
  )

  const draftPrint = useMemo(() => fingerprint(toSpec(draft)), [draft])

  const recheck = useMutation({
    mutationFn: async () => {
      await autosave.flush()
      const print = fingerprint(toSpec(current.current))
      const out = await runChecks(app.id)
      return { out, print }
    },
    onSuccess: ({ out, print }) => {
      setResults(out)
      setCheckedPrint(print)
      writeChecked(app.id, print)
      qc.setQueryData<ApplicationDetail>(studioKeys.application(app.id), (a) =>
        a ? { ...a, check_results: out } : a
      )
    },
  })

  const checkState: CheckState =
    checkedPrint === null
      ? "unchecked"
      : checkedPrint === draftPrint
        ? "current"
        : "stale"

  return {
    draft,
    setDraft,
    saveState: autosave.state,
    saveError: autosave.error,
    flush: autosave.flush,
    results,
    setResults,
    checkState,
    recheck,
  }
}
export type DraftApi = ReturnType<typeof useDraft>
