import { useCallback, useEffect, useRef, useState } from "react"

export type SaveState = "idle" | "pending" | "saving" | "saved" | "error"

/**
 * Debounced autosave. Call `touch(next)` on every edit; the latest value is saved once
 * the owner pauses. `flush` saves at once (used on leaving the page).
 */
export function useAutosave<T>(
  save: (value: T) => Promise<unknown>,
  delay = 700
) {
  const [state, setState] = useState<SaveState>("idle")
  const [error, setError] = useState<string | null>(null)
  const latest = useRef<T | null>(null)
  const dirty = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveRef = useRef(save)
  useEffect(() => {
    saveRef.current = save
  })

  const run = useCallback(async () => {
    if (!dirty.current || latest.current === null) return
    dirty.current = false
    setState("saving")
    try {
      await saveRef.current(latest.current)
      setError(null)
      setState(dirty.current ? "pending" : "saved")
    } catch (e) {
      dirty.current = true
      setError(e instanceof Error ? e.message : "Could not save.")
      setState("error")
    }
  }, [])

  const touch = useCallback(
    (value: T) => {
      latest.current = value
      dirty.current = true
      setState("pending")
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => void run(), delay)
    },
    [delay, run]
  )

  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current)
    await run()
  }, [run])

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
      if (dirty.current) void run()
    },
    [run]
  )

  return { state, error, touch, flush }
}
