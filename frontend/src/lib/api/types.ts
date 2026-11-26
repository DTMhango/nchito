/**
 * The one import point for API types. Everything is generated from `docs/openapi.json`
 * (`npm run gen:api` writes `schema.d.ts`);
 */
import type {
  components,
  operations,
  paths as GeneratedPaths,
} from "./schema.d"

export type { components, operations }
export type paths = GeneratedPaths
/** Every named schema in the contract: `Schemas["JobSummary"]`. */
export type Schemas = components["schemas"]

export type ApiErrorBody = {
  detail?:
    | string
    | { msg: string; loc?: (string | number)[] }[]
    /** A coded refusal from the apply layer (`@/lib/api/refusals`). */
    | { code?: string; reason?: string; [extra: string]: unknown }
}

export type SetupStatus = Schemas["SetupStatus"]
export type OwnerCreate = Schemas["OwnerCreate"]
export type LoginRequest = Schemas["LoginIn"]
export type Me = Schemas["Me"]
export type Health = Schemas["Health"]
export type ThemeInput = Schemas["ThemeIn"]
export type JobCaptureRequest = Schemas["CaptureIn"]
export type JobCaptureResponse = Schemas["CaptureOut"]
export type AutopilotState = Schemas["AutopilotState"]
export type PauseItem = AutopilotState["summary"]["cancelled"][number]
export type AnswerUse = Schemas["AnswerUseOut"]
export type Session = Schemas["SessionOut"]
export type Waiver = Schemas["WaiverOut"]
export type WaiverIn = Schemas["WaiverIn"]
export type RecheckResult = Schemas["RecheckOut"]
export type { Appearance, Theme } from "@/themes/schema"
