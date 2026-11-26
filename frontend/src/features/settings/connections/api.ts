/** Settings > Connections: mail, Drive, Telegram, webhook, search API. Typed from the generated contract. */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type Connection = S["ConnectionOut"]
export type ConnectionCreate = S["ConnectionCreate"]
export type ConnectionUpdate = S["ConnectionUpdate"]
export type ConnectionTest = S["ConnectionTestOut"]
export type Provider = Connection["provider"]

/** The providers this screen owns. The AI providers live on Settings > AI. */
export const CONNECTION_PROVIDERS = [
  "gmail",
  "imap_smtp",
  "gdrive",
  "telegram",
  "webhook",
  "search_api",
] as const satisfies readonly Provider[]
export type ConnectionProvider = (typeof CONNECTION_PROVIDERS)[number]

export const connectionKeys = { all: ["connections"] as const }

export const connectionsQuery = () =>
  queryOptions({
    queryKey: connectionKeys.all,
    queryFn: async () =>
      (await unwrap(api.GET("/api/connections"))).filter((c) =>
        (CONNECTION_PROVIDERS as readonly string[]).includes(c.provider)
      ),
  })

export const createConnection = (body: ConnectionCreate) =>
  unwrap(
    api.POST("/api/connections", { body })
  ) as unknown as Promise<Connection>
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
export const oauthStart = (provider: "gmail" | "gdrive") =>
  unwrap(
    api.POST("/api/connections/oauth/{provider}/start", {
      params: { path: { provider } },
    })
  )
