/**
 * Endpoints being added in a parallel stream and not yet in `docs/openapi.json`, in the
 * shape `openapi-typescript` emits. When `npm run gen:api` picks them up, delete the entry
 * here (and this file once it is empty): the generated types then take over.
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
      responses: { 200: Json<{ revoked: number }>; 204: Empty }
    }
  }
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
