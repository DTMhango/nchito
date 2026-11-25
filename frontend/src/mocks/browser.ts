import { setupWorker } from "msw/browser"
import { handlers } from "./handlers"
import { loadBrowserDb } from "./db"

/** Start the mock backend in the browser (VITE_MOCK=1). */
export async function startMockBackend() {
  loadBrowserDb()
  const worker = setupWorker(...handlers)
  await worker.start({ onUnhandledFrame: "bypass", quiet: true })
}
