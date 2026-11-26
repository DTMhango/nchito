/** Interview pack endpoints (`backend/app/api/routers/interview.py`), typed from the contract. */
import { queryOptions } from "@tanstack/react-query"
import { api, ApiError, isApiError, unwrap } from "@/lib/api/client"
import {
  isOpen,
  type InterviewPack,
  type PracticeIn,
  type StoryEdit,
} from "./shapes"

/** How often to look again while a pack is being built. */
export const PACK_POLL_MS = import.meta.env.MODE === "test" ? 40 : 1500

export const packKeys = {
  pack: (jobId: string) => ["jobs", jobId, "interview-pack"] as const,
  estimate: (jobId: string) =>
    ["jobs", jobId, "interview-pack", "estimate"] as const,
  versions: (jobId: string, section: string) =>
    ["jobs", jobId, "interview-pack", "versions", section] as const,
  practice: (jobId: string) =>
    ["jobs", jobId, "interview-pack", "practice"] as const,
}

const job = (jobId: string) => ({ path: { job_id: jobId } })
const sec = (jobId: string, section: string) => ({
  path: { job_id: jobId, section },
})

/** The refusal code of an API error (`{detail: {code, reason}}`), if any. */
export function refusalCode(e: unknown): string | undefined {
  if (!(e instanceof ApiError)) return undefined
  const d = e.body?.detail
  return d && !Array.isArray(d) && typeof d === "object"
    ? (d.code as string | undefined)
    : undefined
}

/** The pack, or null when none exists yet (404). Polls while generation is queued or running. */
export const packQuery = (jobId: string, enabled = true) =>
  queryOptions({
    queryKey: packKeys.pack(jobId),
    enabled,
    retry: false,
    queryFn: async (): Promise<InterviewPack | null> => {
      try {
        return await unwrap(
          api.GET("/api/jobs/{job_id}/interview-pack", { params: job(jobId) })
        )
      } catch (e) {
        if (isApiError(e, 404)) return null
        throw e
      }
    },
    refetchInterval: (q) =>
      isOpen(q.state.data?.status) ? PACK_POLL_MS : false,
  })

export const estimateQuery = (jobId: string, sections?: string[]) =>
  queryOptions({
    queryKey: [...packKeys.estimate(jobId), sections ?? "all"],
    retry: false,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/interview-pack/estimate", {
          params: { ...job(jobId), query: { sections: sections ?? null } },
        })
      ),
  })

export const versionsQuery = (jobId: string, section: string) =>
  queryOptions({
    queryKey: packKeys.versions(jobId, section),
    queryFn: () =>
      unwrap(
        api.GET(
          "/api/jobs/{job_id}/interview-pack/sections/{section}/versions",
          {
            params: sec(jobId, section),
          }
        )
      ),
  })

export const practiceQuery = (jobId: string, enabled = true) =>
  queryOptions({
    queryKey: packKeys.practice(jobId),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/interview-pack/practice", {
          params: job(jobId),
        })
      ),
  })

/** Queue the pack, or only the listed sections (202; idempotent while a request is open). */
export const generatePack = (jobId: string, sections?: string[]) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/interview-pack", {
      params: job(jobId),
      body: sections?.length ? { sections } : {},
    })
  )

/** 409 `still_queued` while the pack is being generated. */
export const regenerateSection = (jobId: string, section: string) =>
  unwrap(
    api.POST(
      "/api/jobs/{job_id}/interview-pack/sections/{section}/regenerate",
      {
        params: sec(jobId, section),
      }
    )
  )

/** An owner version of a section (checked like a generated one; 422 `invalid_section`). */
export const editSection = (
  jobId: string,
  section: string,
  content: Record<string, unknown>
) =>
  unwrap(
    api.PUT("/api/jobs/{job_id}/interview-pack/sections/{section}", {
      params: sec(jobId, section),
      body: { content },
    })
  )

export const saveNote = (jobId: string, section: string, note: string) =>
  unwrap(
    api.PUT("/api/jobs/{job_id}/interview-pack/sections/{section}/note", {
      params: sec(jobId, section),
      body: { note: note.trim() ? note : null },
    })
  )

export const setFavourite = (
  jobId: string,
  storyId: string,
  favourite: boolean
) =>
  unwrap(
    api.PUT("/api/jobs/{job_id}/interview-pack/stories/{story_id}/favourite", {
      params: { path: { job_id: jobId, story_id: storyId } },
      body: { favourite },
    })
  )

/** 409 `version_conflict` when `base_version` is no longer the current stories version. */
export const editStory = (jobId: string, storyId: string, body: StoryEdit) =>
  unwrap(
    api.PUT("/api/jobs/{job_id}/interview-pack/stories/{story_id}", {
      params: { path: { job_id: jobId, story_id: storyId } },
      body,
    })
  )

export const practise = (jobId: string, body: PracticeIn) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/interview-pack/practice", {
      params: job(jobId),
      body,
    })
  )

export const retryPractice = (practiceId: string) =>
  unwrap(
    api.POST("/api/interview-practice/{practice_id}/retry", {
      params: { path: { practice_id: practiceId } },
    })
  )

export type ExportFormat = "pdf" | "docx" | "txt"

/** Download the pack; returns the sections the server marked flagged (`X-Flagged-Sections`). */
export async function exportPack(
  jobId: string,
  fmt: ExportFormat
): Promise<{ blob: Blob; flagged: string[]; filename: string }> {
  const { data, error, response } = await api.GET(
    "/api/jobs/{job_id}/interview-pack/export",
    { params: { ...job(jobId), query: { fmt } }, parseAs: "blob" }
  )
  if (!response.ok) throw new ApiError(response.status, error)
  const flagged = (response.headers.get("X-Flagged-Sections") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
  const disposition = response.headers.get("Content-Disposition") ?? ""
  const filename =
    /filename="([^"]+)"/.exec(disposition)?.[1] ?? `interview-pack.${fmt}`
  return { blob: data as Blob, flagged, filename }
}
