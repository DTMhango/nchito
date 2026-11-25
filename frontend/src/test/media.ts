/** Emulated prefers-color-scheme for tests. */
let systemDark = false

export function resetSystemDark() {
  systemDark = false
}
const listeners = new Set<(e: MediaQueryListEvent) => void>()

/** Flip the emulated OS colour scheme and notify listeners. */
export function setSystemDark(dark: boolean) {
  systemDark = dark
  for (const l of listeners)
    l({
      matches: dark,
      media: "(prefers-color-scheme: dark)",
    } as MediaQueryListEvent)
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    get matches() {
      return query.includes("prefers-color-scheme: dark") ? systemDark : false
    },
    media: query,
    onchange: null,
    addEventListener: (_: string, l: (e: MediaQueryListEvent) => void) =>
      listeners.add(l),
    removeEventListener: (_: string, l: (e: MediaQueryListEvent) => void) =>
      listeners.delete(l),
    addListener: (l: (e: MediaQueryListEvent) => void) => listeners.add(l),
    removeListener: (l: (e: MediaQueryListEvent) => void) =>
      listeners.delete(l),
    dispatchEvent: () => false,
  }),
})
