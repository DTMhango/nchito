import { api, unwrap } from "@/lib/api/client"
import type { RecheckResult } from "@/lib/api/types"

export type { RecheckResult }

/** Check a posting again: availability, content changes, and whether it was re-scored. */
export const recheckJob = (id: string) =>
  unwrap(
    api.POST("/api/jobs/{job_id}/recheck", {
      params: { path: { job_id: id } },
    })
  )

/** One short sentence for a toast or an inline note. */
export function recheckSummary(r: RecheckResult): string {
  const parts: string[] = []
  if (r.availability_before !== r.availability_after)
    parts.push(
      `Now ${r.availability_after.replace(/_/g, " ")} (was ${r.availability_before.replace(/_/g, " ")}).`
    )
  else parts.push(`Still ${r.availability_after.replace(/_/g, " ")}.`)
  if (r.content_changed)
    parts.push(
      r.changed_fields.length
        ? `Changed: ${r.changed_fields.map((f) => f.replace(/_/g, " ")).join(", ")}.`
        : "The posting changed."
    )
  else parts.push("No changes to the posting.")
  if (r.reassessed) parts.push("Scored again.")
  if (r.note) parts.push(r.note)
  return parts.join(" ")
}
