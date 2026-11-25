import type { components, paths } from "@/lib/api/schema.d"

type S = components["schemas"]

export type GenPaths = paths
export type Campaign = S["CampaignOut"]
export type CampaignInput = S["CampaignIn"]
export type CampaignCriteria = S["CampaignCriteria-Input"]
export type CampaignRule = S["CampaignRule-Input"]
export type ConditionSet = S["ConditionSet-Input"]
export type ConditionGroup = S["Group-Input"]
export type ValueFilter = S["ValueFilter"]
export type RangeFilter = S["RangeFilter"]
export type TextFilter = S["TextFilter"]
export type LocationRule = S["LocationRule"]
export type PayFloor = S["PayFloor"]
export type UnknownDataPolicy = S["UnknownDataPolicy"]
export type AutomationPolicy = S["AutomationPolicy"]
export type CampaignBudget = S["CampaignBudget"]
export type Rubric = S["RubricOut"]
export type RubricBody = S["RubricBody-Input"]
export type RubricCriterion = S["RubricCriterion"]
export type RubricPenalty = S["RubricPenalty-Input"]
export type RubricThresholds = S["RubricThresholds"]
export type BacktestResult = S["BacktestOut"]
export type BacktestRow = S["BacktestRow"]
export type RulePreview = S["RulePreviewOut"]
export type FacetCatalogEntry = S["FacetCatalogEntry"]
export type Source = S["SourceOut"]
export type WatchedEmployer = S["WatchedEmployerOut"]
export type Track = S["TrackOut"]
export type JobSummary = S["JobSummary"]
export type Setting = S["SettingOut"]

export type AutomationMode = NonNullable<AutomationPolicy["mode"]>
export type UnknownChoice = NonNullable<UnknownDataPolicy["pay"]>
export type CampaignStatus = Campaign["status"]
