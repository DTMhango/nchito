/** Settings > Runners: gateway tokens and runner status. Typed from the generated contract. */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type Token = S["TokenOut"]
export type TokenCreate = S["TokenCreate"]
export type TokenCreated = S["TokenCreated"]
export type RunnerStatus = S["RunnerStatus"]
export type Scope = NonNullable<TokenCreate["scopes"]>[number]
export type RunnerKind = TokenCreate["runner_kind"] & string

export const tokenKeys = {
  tokens: ["tokens"] as const,
  runners: ["autopilot", "runners"] as const,
}

export const tokensQuery = () =>
  queryOptions({
    queryKey: tokenKeys.tokens,
    queryFn: () => unwrap(api.GET("/api/tokens")),
  })
/** Same key as the Autopilot channels panel, so both screens share one fetch. */
export const runnerStatusQuery = () =>
  queryOptions({
    queryKey: tokenKeys.runners,
    queryFn: () => unwrap(api.GET("/api/tokens/runners")),
    refetchInterval: 30_000,
  })

export const createToken = (body: TokenCreate) =>
  unwrap(api.POST("/api/tokens", { body }))
export const revokeToken = (id: string) =>
  unwrap(
    api.POST("/api/tokens/{token_id}/revoke", {
      params: { path: { token_id: id } },
    })
  )
export const reinstateToken = (id: string) =>
  unwrap(
    api.POST("/api/tokens/{token_id}/reinstate", {
      params: { path: { token_id: id } },
    })
  )
