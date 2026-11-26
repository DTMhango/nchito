/**
 * Endpoints being added in a parallel stream and not yet in `docs/openapi.json`, in the
 * shape `openapi-typescript` emits (copied from that stream's contract). When `npm run
 * gen:api` picks them up, delete the entry here (and this file once it is empty): the
 * generated types then take over.
 */

/** One signed-in session (Settings > Security). */
export type Session = {
  id: string
  created_at: string
  last_seen_at: string | null
  user_agent: string | null
  ip: string | null
  /** The session making this request. */
  current: boolean
}

type NoParams = { query?: never; header?: never; path?: never; cookie?: never }
type IdParam = {
  query?: never
  header?: never
  path: { session_id: string }
  cookie?: never
}
type ItemParam = {
  query?: never
  header?: never
  path: { item_id: string }
  cookie?: never
}
type WaiverParam = {
  query?: never
  header?: never
  path: { waiver_id: string }
  cookie?: never
}
type Json<T> = {
  headers: { [name: string]: unknown }
  content: { "application/json": T }
}
type Empty = { headers: { [name: string]: unknown }; content?: never }

export interface PendingPaths {
  "/api/auth/sessions": {
    parameters: NoParams
    get: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<Session[]> }
    }
  }
  "/api/auth/sessions/{session_id}": {
    parameters: IdParam
    delete: {
      parameters: IdParam
      requestBody?: never
      responses: { 204: Empty }
    }
  }
  "/api/auth/sessions/revoke-others": {
    parameters: NoParams
    post: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<{ [key: string]: number }> }
    }
  }
  "/api/kit/answers/{item_id}/usage": {
    parameters: ItemParam
    get: {
      parameters: ItemParam
      requestBody?: never
      responses: { 200: Json<AnswerUse[]> }
    }
  }
  "/api/kit/guardrails/{item_id}/waivers": {
    parameters: ItemParam
    post: {
      parameters: ItemParam
      requestBody: { content: { "application/json": WaiverIn } }
      responses: { 201: Json<Waiver> }
    }
  }
  "/api/kit/guardrail-waivers": {
    parameters: NoParams
    get: {
      parameters: {
        query?: { application_id?: string | null; guardrail_id?: string | null }
        header?: never
        path?: never
        cookie?: never
      }
      requestBody?: never
      responses: { 200: Json<Waiver[]> }
    }
  }
  "/api/kit/guardrail-waivers/{waiver_id}": {
    parameters: WaiverParam
    delete: {
      parameters: WaiverParam
      requestBody?: never
      responses: { 204: Empty }
    }
  }
}

/** An open application (before submission) whose packet or pending actions use an answer. */
export type AnswerUse = {
  application_id: string
  job_id: string
  job_title: string
  employer: string
  stage: string
  via: "packet" | "pending_action"
}

/** A "block, waivable once" guardrail waived for one application, with a reason. */
export type WaiverIn = { application_id: string; reason: string }
export type Waiver = {
  id: string
  created_at: string
  updated_at: string
  guardrail_id: string
  application_id: string
  reason: string
  waived_by: string
}

/**
 * `POST /api/jobs/{id}/recheck` now returns what the recheck found rather than the job
 * (the contract in docs/openapi.json still says JobDetail until it is regenerated).
 */
export type RecheckResult = {
  job: import("./schema.d").components["schemas"]["JobDetail"]
  availability_before: string
  availability_after: string
  content_changed: boolean
  changed_fields: string[]
  reassessed: boolean
  note: string | null
}
