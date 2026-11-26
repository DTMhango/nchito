import { http, HttpResponse } from "msw"
import type { InsightsReport } from "@/features/insights/api"
import { emptyInsights, insightsDataset } from "@/mocks/dataset/insights"

let mode: "data" | "empty" = "data"

/** Tests switch the mock between the invented dataset and a fresh install. */
export const insightsMock = {
  reset: () => {
    mode = "data"
  },
  setEmpty: () => {
    mode = "empty"
  },
}

export const insightsHandlers = [
  http.get("*/api/insights", ({ request }) => {
    const q = new URL(request.url).searchParams
    const report: InsightsReport =
      mode === "empty" ? emptyInsights() : insightsDataset()
    report.filters = {
      ...report.filters,
      country: q.get("country"),
      campaign_id: q.get("campaign_id"),
    }
    return HttpResponse.json(report)
  }),
]
