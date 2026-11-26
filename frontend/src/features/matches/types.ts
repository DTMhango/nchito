/** Matches API types, taken from the generated contract (`src/lib/api/schema.d.ts`). */
import type { components, paths } from "@/lib/api/schema.d"

type S = components["schemas"]

export type GenPaths = paths
export type JobSummary = S["JobSummary"]
export type JobDetail = S["JobDetail"]
export type JobListOut = S["JobListOut"]
export type JobPatch = S["JobPatch"]
export type JobGroup = S["JobGroup"]
export type JobFacets = S["JobFacets"]
export type Triage = JobSummary["triage"]
export type PayOut = S["PayOut"]
export type FacetCatalogEntry = S["FacetCatalogEntry"]
export type BulkActionIn = S["BulkActionIn"]
export type BulkAction = BulkActionIn["action"]
export type BulkActionOut = S["BulkActionOut"]
export type WhyOut = S["WhyOut"]
export type WhyRule = S["WhyRule"]
export type ConditionResult = S["ConditionResult"]
export type SavedViewOut = S["SavedViewOut"]
export type SavedViewIn = S["SavedViewIn"]
export type TagRuleOut = S["TagRuleOut"]
export type TagRuleIn = S["TagRuleIn"]
export type CustomFacetOut = S["CustomFacetOut"]
export type CustomFacetIn = S["CustomFacetIn"]
export type BackfillEstimate = S["BackfillEstimate"]
export type AssessmentOut = S["AssessmentOut"]
export type RubricOut = S["RubricOut"]
export type FactOut = S["FactOut"]
export type CampaignOut = S["CampaignOut"]
export type CampaignRuleIn = S["CampaignRule-Input"]
export type RulePreviewOut = S["RulePreviewOut"]
export type RescoreOut = S["RescoreOut"]
export type AppliedMyselfIn = S["AppliedMyselfIn"]

export type Scalar = string | number | boolean
export type ValueFilter = {
  type: "values"
  facet: string
  include: Scalar[]
  exclude: Scalar[]
  match: "any" | "all"
}
export type RangeFilter = {
  type: "range"
  facet: string
  min?: number | null
  max?: number | null
  not_stated: "include" | "exclude"
}
export type TextFilter = { type: "text"; query: string; fields: string[] }
export type Group = {
  type: "group"
  op: "and" | "or"
  negate: boolean
  conditions: Condition[]
}
export type Condition = ValueFilter | RangeFilter | TextFilter | Group
export type ConditionSet = { version: 1; root: Group }
