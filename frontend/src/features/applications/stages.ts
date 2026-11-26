import type { Stage } from "@/components/stage-pill"
import { STAGE_META } from "@/components/stage-pill"
import type { KanbanColumn } from "@/components/kanban-board"

/**
 * Board columns (DESIGN 4, 10.3). The four end states share Closed; `accepted` sits with
 * Offer. Column ids are stage names, except "closed".
 */
export const BOARD_COLUMNS: KanbanColumn[] = [
  { id: "shortlisted", title: "Shortlisted" },
  { id: "tailoring", title: "Tailoring" },
  { id: "ready", title: "Ready" },
  { id: "applying", title: "Applying" },
  { id: "submitted_unconfirmed", title: "Unconfirmed" },
  { id: "submitted", title: "Submitted" },
  { id: "screening", title: "Screening" },
  { id: "interview", title: "Interview" },
  { id: "offer", title: "Offer" },
  { id: "closed", title: "Closed" },
]

const CLOSED: Stage[] = ["rejected", "withdrawn", "closed", "skipped"]

export const columnOf = (stage: Stage): string =>
  CLOSED.includes(stage) ? "closed" : stage === "accepted" ? "offer" : stage

export const columnTitle = (id: string) =>
  BOARD_COLUMNS.find((c) => c.id === id)?.title ?? id

const PRE_SUBMIT: Stage[] = [
  "shortlisted",
  "tailoring",
  "ready",
  "applying",
  "submitted_unconfirmed",
]
const POST_SUBMIT: Stage[] = ["submitted", "screening", "interview", "offer"]

export type MoveCheck =
  | { kind: "stage"; stage: Stage }
  | { kind: "applied-myself" }
  | { kind: "refused"; reason: string }

const refuse = (reason: string): MoveCheck => ({ kind: "refused", reason })

/**
 * Decides what dropping a card on a column means. Nothing here ever marks an application
 * submitted: the Submitted and Unconfirmed columns route to "I applied myself" (DESIGN 18.2),
 * which records the owner's own submission. Runner-owned stages cannot be set by hand.
 */
export function checkMove(from: Stage, toColumn: string): MoveCheck {
  const fromCol = columnOf(from)
  if (fromCol === toColumn) return refuse("It is already in that column.")

  if (toColumn === "applying")
    return refuse(
      "Applying is set by the runner while it sends the application. You can't move a card there."
    )
  if (toColumn === "submitted_unconfirmed")
    return refuse(
      "Unconfirmed means a send went out without a recorded outcome. Only the dispatch record sets it. If you applied yourself, drop the card on Submitted."
    )
  if (from === "applying")
    return refuse(
      "The runner is working on this application. Wait for it to finish, or cancel the dispatch from the job page."
    )

  if (toColumn === "closed") return { kind: "stage", stage: "closed" }

  if (fromCol === "closed") {
    return toColumn === "shortlisted"
      ? { kind: "stage", stage: "shortlisted" }
      : refuse(
          "A closed application can only be reopened as Shortlisted. Move it there first."
        )
  }

  if (toColumn === "submitted") {
    if (PRE_SUBMIT.includes(from)) return { kind: "applied-myself" }
    return refuse("It is already submitted.")
  }

  if (POST_SUBMIT.includes(from) || from === "accepted") {
    const order = POST_SUBMIT
    const ti = order.indexOf(toColumn as Stage)
    if (ti < 0)
      return refuse(
        "A submitted application can't go back before submission. Its submission record is permanent."
      )
    const fi = from === "accepted" ? order.length - 1 : order.indexOf(from)
    return ti > fi
      ? { kind: "stage", stage: toColumn as Stage }
      : refuse(
          `It has already passed ${columnTitle(toColumn)}. Stages only move forward after submission.`
        )
  }

  // from is shortlisted, tailoring, ready or unconfirmed
  if (["screening", "interview", "offer"].includes(toColumn))
    return refuse(
      `Apply first. A role can't reach ${columnTitle(toColumn)} before it was submitted. If you applied yourself, drop it on Submitted.`
    )
  if (from === "submitted_unconfirmed")
    return refuse("Confirm the submission by dropping the card on Submitted.")
  const order: Stage[] = ["shortlisted", "tailoring", "ready"]
  const fi = order.indexOf(from)
  const ti = order.indexOf(toColumn as Stage)
  if (ti < 0) return refuse("That move isn't allowed.")
  if (Math.abs(ti - fi) > 1)
    return refuse(
      `Move it one step at a time: ${STAGE_META[order[fi + Math.sign(ti - fi)]].label} comes next.`
    )
  if (toColumn === "ready")
    return refuse(
      "Ready is set when you approve the tailored packet in Studio. Open the application to approve it."
    )
  return { kind: "stage", stage: toColumn as Stage }
}
