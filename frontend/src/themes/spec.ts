/**
 * Typed view of `token-spec.json`, the single source of truth for token groups, value types,
 * contrast uses, bundled fonts and WCAG levels (shared verbatim with the backend).
 */
import raw from "./token-spec.json"

export type TokenType =
  "colour" | "shadow" | "weight" | "track" | "factor" | "length" | "enum"
export type ContrastUse = "body" | "text" | "ui" | "graphic"

export type TokenSpec = {
  group: string
  type: TokenType
  label: string
  required?: boolean
  ground?: boolean
  status?: boolean
  use?: ContrastUse
  on?: string[]
  min?: number
  max?: number
  values?: string[]
}

export type LevelSpec = {
  label: string
  aa: number
  aaa: number | null
  blocking: boolean
}

type Spec = {
  version: number
  fonts: Record<string, "sans" | "serif" | "mono">
  groups: { key: string; label: string }[]
  levels: Record<ContrastUse, LevelSpec>
  tokens: Record<string, TokenSpec>
  limits: {
    tokens_per_mode: number
    value_length: number
    chart_colours: number
  }
}

export const TOKEN_SPEC = raw as Spec

export const TOKEN_NAMES = Object.keys(TOKEN_SPEC.tokens)
export const FONT_FAMILIES = Object.keys(TOKEN_SPEC.fonts)
export const GROUND_TOKENS = TOKEN_NAMES.filter(
  (k) => TOKEN_SPEC.tokens[k].ground
)
export const STATUS_TOKENS = TOKEN_NAMES.filter(
  (k) => TOKEN_SPEC.tokens[k].status
)
export const COLOUR_TOKEN_NAMES = new Set(
  TOKEN_NAMES.filter((k) => TOKEN_SPEC.tokens[k].type === "colour")
)

export function tokensInGroup(group: string): string[] {
  return TOKEN_NAMES.filter((k) => TOKEN_SPEC.tokens[k].group === group)
}
