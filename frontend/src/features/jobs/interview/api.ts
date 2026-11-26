import { queryOptions } from "@tanstack/react-query"
import { isApiError } from "@/lib/api/client"
import {
  pending,
  type InterviewEstimate,
  type InterviewPack,
  type PackSectionKey,
  type PracticeFeedback,
} from "../w3-pending-types"

const base = (appId: string) => `/api/applications/${appId}/interview-pack`

/** How often to look again while a pack is being built. */
export const PACK_POLL_MS = import.meta.env.MODE === "test" ? 40 : 1500

export const packKeys = {
  pack: (appId: string) => ["applications", appId, "interview-pack"] as const,
  estimate: (appId: string) =>
    ["applications", appId, "interview-pack", "estimate"] as const,
}

/** The pack, or null when none has been built yet (404). Polls while it is generating. */
export const packQuery = (appId: string | null | undefined) =>
  queryOptions({
    queryKey: packKeys.pack(appId ?? "none"),
    enabled: !!appId,
    retry: false,
    queryFn: async () => {
      try {
        return await pending<InterviewPack>("GET", base(appId!))
      } catch (e) {
        if (isApiError(e, 404)) return null
        throw e
      }
    },
    refetchInterval: (q) =>
      q.state.data?.status === "generating" ? PACK_POLL_MS : false,
  })

export const estimateQuery = (appId: string, enabled: boolean) =>
  queryOptions({
    queryKey: packKeys.estimate(appId),
    enabled,
    queryFn: () => pending<InterviewEstimate>("GET", `${base(appId)}/estimate`),
  })

export const generatePack = (appId: string) =>
  pending<InterviewPack>("POST", base(appId), {})
export const resumePack = (appId: string) =>
  pending<InterviewPack>("POST", `${base(appId)}/resume`, {})
export const saveNotes = (appId: string, key: PackSectionKey, notes: string) =>
  pending<InterviewPack>("PUT", `${base(appId)}/sections/${key}/notes`, {
    notes,
  })
export const saveItem = (
  appId: string,
  key: PackSectionKey,
  itemId: string,
  body: { text: string; fact_ids: string[] }
) =>
  pending<InterviewPack>(
    "PUT",
    `${base(appId)}/sections/${key}/items/${itemId}`,
    body
  )
export const regenerateSection = (appId: string, key: PackSectionKey) =>
  pending<InterviewPack>(
    "POST",
    `${base(appId)}/sections/${key}/regenerate`,
    {}
  )
export const restoreVersion = (
  appId: string,
  key: PackSectionKey,
  version: number
) =>
  pending<InterviewPack>("POST", `${base(appId)}/sections/${key}/restore`, {
    version,
  })
export const setFavourite = (
  appId: string,
  itemId: string,
  favourite: boolean
) =>
  pending<InterviewPack>("PUT", `${base(appId)}/items/${itemId}/favourite`, {
    favourite,
  })
export const practice = (
  appId: string,
  body: { question_id: string; draft: string }
) => pending<PracticeFeedback>("POST", `${base(appId)}/practice`, body)

export type ExportFormat = "docx" | "pdf" | "txt"
export const exportUrl = (appId: string, format: ExportFormat) =>
  `${base(appId)}/export?format=${format}`
