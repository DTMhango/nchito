import { useCallback, useMemo, useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useAutosave } from "@/features/campaigns/use-autosave"
import { isApiError } from "@/lib/api/client"
import { runChecks, saveSpec, studioKeys, type SpecState } from "./api"
import { fingerprint, toDraft, toSpec, type Draft } from "./draft"

export type CheckState = "current" | "stale" | "unchecked"

/**
 * Whether the server's check results describe what is on screen. The server says whether its
 * latest version is checked (`SpecStateOut.checked`, `stale_reasons`); edits not saved yet are
 * stale too, because no check has seen them.
 */
export function checkStateOf(state: SpecState, unsaved: boolean): CheckState {
  if (unsaved) return "stale"
  if (state.checked) return "current"
  if (state.stale_reasons.length > 0) return "stale"
  return "unchecked"
}

/** 409 on save or check: the application has gone out, or there is no draft to check. */
export function draftError(e: unknown, action: "save" | "check"): string {
  if (isApiError(e, 409))
    return action === "save"
      ? "This application has already gone out, so its documents can no longer change."
      : "There is no draft to check yet."
  return e instanceof Error ? e.message : "Something went wrong."
}

/**
 * The editable draft of one application's spec: autosaved after a pause (each save stores an
 * owner version and runs the code checks on the server), and the check state from the server.
 */
export function useDraft(applicationId: string, state: SpecState) {
  const qc = useQueryClient()
  const [draft, setDraftState] = useState<Draft>(() => toDraft(state.spec))
  const current = useRef(draft)
  const refreshState = useCallback(
    () => qc.invalidateQueries({ queryKey: studioKeys.spec(applicationId) }),
    [applicationId, qc]
  )

  const save = useCallback(
    async (d: Draft) => {
      const out = await saveSpec(applicationId, toSpec(d)).catch((e) => {
        throw isApiError(e, 409) ? new Error(draftError(e, "save")) : e
      })
      qc.setQueryData(studioKeys.application(applicationId), out)
      await refreshState()
      void qc.invalidateQueries({ queryKey: ["applications"] })
    },
    [applicationId, qc, refreshState]
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

  const savedPrint = useMemo(() => fingerprint(state.spec), [state.spec])
  const draftPrint = useMemo(() => fingerprint(toSpec(draft)), [draft])

  const recheck = useMutation({
    mutationFn: async () => {
      await autosave.flush()
      return runChecks(applicationId)
    },
    onSuccess: (out) => {
      qc.setQueryData<SpecState>(studioKeys.spec(applicationId), (s) =>
        s ? { ...s, check_results: out } : s
      )
      void refreshState()
    },
  })

  return {
    draft,
    setDraft,
    saveState: autosave.state,
    saveError: autosave.error,
    flush: autosave.flush,
    results: state.check_results,
    checkState: checkStateOf(state, draftPrint !== savedPrint),
    staleReasons: state.stale_reasons,
    blocking: state.status === "block",
    recheck,
    recheckError: recheck.error ? draftError(recheck.error, "check") : null,
  }
}
export type DraftApi = ReturnType<typeof useDraft>
