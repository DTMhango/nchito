/**
 * The one import point for API types. Everything is generated from `docs/openapi.json`
 * (`npm run gen:api` writes `schema.d.ts`); `pending.ts` adds the few endpoints a parallel
 * stream is adding and the contract does not list yet.
 */
import type {
  components,
  operations,
  paths as GeneratedPaths,
} from "./schema.d"
import type { PendingPaths } from "./pending"

export type { components, operations }
export type paths = GeneratedPaths & PendingPaths
/** Every named schema in the contract: `Schemas["JobSummary"]`. */
export type Schemas = components["schemas"]

export type ApiErrorBody = {
  detail?: string | { msg: string; loc?: (string | number)[] }[]
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
export type { AnswerUse, Session, Waiver, WaiverIn } from "./pending"
export type { Appearance, Theme } from "@/themes/schema"
