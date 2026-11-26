/** Interview schedule calls (`routers/events.py`), typed from the generated contract. */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type EventOut = S["EventOut"]
export type EventIn = S["EventIn"]
export type EventUpdate = S["EventUpdate"]
export type ConfirmIn = S["ConfirmIn"]
export type RescheduleIn = S["RescheduleIn"]
export type DebriefIn = S["DebriefIn"]
export type DebriefOut = S["DebriefOut"]
export type EventCandidate = S["EventCandidate"]

export const scheduleKeys = {
  job: (jobId: string) => ["jobs", jobId, "events"] as const,
  upcoming: ["interview-events", "upcoming"] as const,
}

const ev = (id: string) => ({ path: { event_id: id } })

export const jobEventsQuery = (jobId: string) =>
  queryOptions({
    queryKey: scheduleKeys.job(jobId),
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/events", {
          params: { path: { job_id: jobId } },
        })
      ),
  })

export const upcomingEventsQuery = () =>
  queryOptions({
    queryKey: scheduleKeys.upcoming,
    queryFn: () => unwrap(api.GET("/api/interview-events/upcoming")),
  })

export const createEvent = (jobId: string, body: EventIn) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/events", {
      params: { path: { job_id: jobId } },
      body,
    })
  )
export const updateEvent = (id: string, body: EventUpdate) =>
  unwrap(api.PUT("/api/interview-events/{event_id}", { params: ev(id), body }))
export const confirmEvent = (id: string, body: ConfirmIn) =>
  unwrap(
    api.POST("/api/interview-events/{event_id}/confirm", {
      params: ev(id),
      body,
    })
  )
export const rescheduleEvent = (id: string, body: RescheduleIn) =>
  unwrap(
    api.POST("/api/interview-events/{event_id}/reschedule", {
      params: ev(id),
      body,
    })
  )
export const cancelEvent = (id: string) =>
  unwrap(
    api.POST("/api/interview-events/{event_id}/cancel", { params: ev(id) })
  )
export const debriefEvent = (id: string, body: DebriefIn) =>
  unwrap(
    api.POST("/api/interview-events/{event_id}/debrief", {
      params: ev(id),
      body,
    })
  )
export const icsUrl = (id: string) => `/api/interview-events/${id}/ics`
