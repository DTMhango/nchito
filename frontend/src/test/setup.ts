import "@testing-library/jest-dom/vitest"
import { cleanup, configure } from "@testing-library/react"
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest"
import { server } from "./server"
import { db } from "@/mocks/db"
import { resetAllMocks } from "@/mocks/reset"
import { resetSystemDark } from "./media"

// Screens are lazy route chunks; the first import of a chunk under a parallel run can take
// longer than Testing Library's 1 s default.
configure({ asyncUtilTimeout: 5000 })

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
