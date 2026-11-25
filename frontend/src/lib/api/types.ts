/**
 * The one import point for API types. Swap `./schema` for the generated file here
 * (see the header of schema.ts) and nothing else needs to change.
 */
export type { paths } from "./schema"
export type {
  ApiErrorBody,
  AutopilotState,
  Health,
  JobCaptureRequest,
  JobCaptureResponse,
  LoginRequest,
  Me,
  OwnerCreate,
  PauseItem,
  SetupStatus,
  ThemeInput,
} from "./schema"
export type { Appearance, Theme } from "@/themes/schema"
