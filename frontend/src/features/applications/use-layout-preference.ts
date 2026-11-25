import { useCallback, useState } from "react"

export type Layout = "board" | "table"

/** Per-device preference (DESIGN 10.3: "remembered per device"), not synced to the server. */
export const LAYOUT_KEY = "nchito.applications.layout"

function read(): Layout {
  try {
    return window.localStorage.getItem(LAYOUT_KEY) === "table"
      ? "table"
      : "board"
  } catch {
    return "board"
  }
}

export function useLayoutPreference() {
  const [layout, setLayoutState] = useState<Layout>(read)
  const setLayout = useCallback((next: Layout) => {
    setLayoutState(next)
    try {
      window.localStorage.setItem(LAYOUT_KEY, next)
    } catch {
      /* private mode: the choice lasts for this visit only */
    }
  }, [])
  return [layout, setLayout] as const
}
