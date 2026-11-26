/**
 * Settings > AI: typed calls against the generated OpenAPI types (`schema.d.ts`), query keys
 * and options. Feature code in this folder imports from here only.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type Connection = S["ConnectionOut"]
export type ConnectionCreate = S["ConnectionCreate"]
export type ConnectionUpdate = S["ConnectionUpdate"]
export type Route = S["RouteOut"]
export type RouteTest = S["RouteTestOut"]
export type Price = S["PriceOut"]
export type PriceIn = S["PriceIn"]
export type SpendSummary = S["SpendSummary"]
export type SpendMeterData = S["SpendMeter"]
export type Prompt = S["PromptOut"]
export type Setting = S["SettingOut"]

export const aiKeys = {
  all: ["ai"] as const,
  connections: ["ai", "connections"] as const,
  routing: ["ai", "routing"] as const,
  prices: ["ai", "prices"] as const,
  spend: ["ai", "spend"] as const,
  meter: ["ai", "spend", "meter"] as const,
  prompts: ["ai", "prompts"] as const,
  setting: (key: string) => ["ai", "setting", key] as const,
}

/** Provider records the AI screen manages (other connections live elsewhere). */
export const LLM_PROVIDERS = ["anthropic", "openai_compatible"] as const

export const listConnections = () => unwrap(api.GET("/api/connections"))
export const createConnection = (body: ConnectionCreate) =>
  unwrap(api.POST("/api/connections", { body }))
export const updateConnection = (id: string, body: ConnectionUpdate) =>
  unwrap(
    api.PUT("/api/connections/{connection_id}", {
      params: { path: { connection_id: id } },
      body,
    })
  )
export const deleteConnection = (id: string) =>
  unwrap(
    api.DELETE("/api/connections/{connection_id}", {
      params: { path: { connection_id: id } },
    })
  )
export const testConnection = (id: string) =>
  unwrap(
    api.POST("/api/connections/{connection_id}/test", {
      params: { path: { connection_id: id } },
    })
  )

export const listRouting = () => unwrap(api.GET("/api/ai/routing"))
export const testRoute = (stage: string, model?: string) =>
  unwrap(api.POST("/api/ai/routing/test", { body: { stage, model } }))
export const activateRoute = (stage: string, model: string) =>
  unwrap(api.POST("/api/ai/routing/activate", { body: { stage, model } }))

export const listPrices = () => unwrap(api.GET("/api/ai/prices"))
export const replacePrices = (prices: PriceIn[]) =>
  unwrap(api.PUT("/api/ai/prices", { body: { prices } }))
export const resetPrices = () => unwrap(api.POST("/api/ai/prices/reset"))

export const getSpend = () => unwrap(api.GET("/api/ai/spend"))
export const getSpendMeter = () => unwrap(api.GET("/api/ai/spend/meter"))

export const listPrompts = () => unwrap(api.GET("/api/kit/prompts"))
export const savePrompt = (stage: string, text: string, note?: string) =>
  unwrap(api.POST("/api/kit/prompts", { body: { stage, text, note } }))
export const activatePrompt = (id: string) =>
  unwrap(
    api.POST("/api/kit/prompts/{item_id}/activate", {
      params: { path: { item_id: id } },
    })
  )

export const getSetting = (key: string) =>
  unwrap(api.GET("/api/settings/{key}", { params: { path: { key } } }))
export const putSetting = (key: string, value: unknown) =>
  unwrap(
    api.PUT("/api/settings/{key}", {
      params: { path: { key } },
      body: { value },
    })
  )

export const connectionsQuery = () =>
  queryOptions({ queryKey: aiKeys.connections, queryFn: listConnections })
export const routingQuery = () =>
  queryOptions({ queryKey: aiKeys.routing, queryFn: listRouting })
export const pricesQuery = () =>
  queryOptions({ queryKey: aiKeys.prices, queryFn: listPrices })
export const spendQuery = () =>
  queryOptions({ queryKey: aiKeys.spend, queryFn: getSpend })
export const spendMeterQuery = () =>
  queryOptions({
    queryKey: aiKeys.meter,
    queryFn: getSpendMeter,
    retry: false,
    staleTime: 60_000,
  })
export const promptsQuery = () =>
  queryOptions({ queryKey: aiKeys.prompts, queryFn: listPrompts })
export const settingQuery = (key: string) =>
  queryOptions({
    queryKey: aiKeys.setting(key),
    queryFn: () => getSetting(key),
  })

export const STAGE_LABELS: Record<string, string> = {
  extract: "Extract and normalise",
  classify_email: "Classify email",
  score: "Score",
  custom_facet: "Custom facets",
  tailor: "Tailor",
  claim_check: "Claim check",
  browser_agent: "Browser agent",
  interview: "Interview prep",
  import: "Import",
}
export const stageLabel = (stage: string) => STAGE_LABELS[stage] ?? stage
