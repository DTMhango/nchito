// Launch a headless Chromium for scripts: Playwright's own build if installed,
// otherwise the installed Chrome or Edge.
import { chromium } from "playwright"

export async function launch() {
  for (const opts of [{}, { channel: "chrome" }, { channel: "msedge" }]) {
    try {
      return await chromium.launch({ headless: true, ...opts })
    } catch {
      /* try the next */
    }
  }
  throw new Error("No Chromium found. Run: npx playwright install chromium")
}
