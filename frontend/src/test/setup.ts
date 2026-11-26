import "@testing-library/jest-dom/vitest"
import { cleanup, configure } from "@testing-library/react"
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest"
import { server } from "./server"
import { db } from "@/mocks/db"
import { resetAllMocks } from "@/mocks/reset"
import { resetSystemDark } from "./media"

// Screens are lazy route chunks. The first query in a file waits for that chunk's import, which
// takes ~3 s alone and over 5 s when the full parallel run shares the CPU with other work, so
// queries wait up to 10 s (Testing Library's default is 1 s). Only a failing query uses it.
configure({ asyncUtilTimeout: 10_000 })
// A test's own budget must exceed one query's wait; otherwise the test times out at the same
// moment as its first slow query, with no message about what it was waiting for.
vi.setConfig({ testTimeout: 20_000 })

// ---- browser APIs jsdom lacks ----
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??=
  ResizeObserverStub as unknown as typeof ResizeObserver
Element.prototype.scrollIntoView ??= vi.fn()
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}
if (!("CSS" in globalThis) || !CSS.escape) {
  ;(globalThis as { CSS?: { escape: (s: string) => string } }).CSS = {
    escape: (s: string) => s.replace(/["\\]/g, "\\$&"),
  }
}

// ---- mock backend ----
beforeAll(() => server.listen({ onUnhandledFrame: "error" }))
beforeEach(() => {
  db.reset("signed-in")
  resetAllMocks()
  localStorage.clear()
  resetSystemDark()
})
afterEach(() => {
  cleanup()
  server.resetHandlers()
  document.documentElement.removeAttribute("style")
  document.documentElement.className = ""
})
afterAll(() => server.close())
