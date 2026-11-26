/**
 * "Send for approval": the server prepares the packet the way the pipeline does
 * (`POST /applications/{id}/packet/prepare`): it renders the checked CV and letter, picks the
 * channel, builds the packet and runs the approval policy. Nothing here decides any of that; the
 * Studio only says which templates were picked and whether the owner applies themself.
 */
import { explainError, type Explained } from "@/lib/api/refusals"
import { preparePacket, type PacketPrepareIn, type RenderKind } from "./api"

export type SendChannel = PacketPrepareIn["channel"] & string

export const prepareBody = (
  templates: Record<RenderKind, string>,
  channel: SendChannel
): PacketPrepareIn => ({
  channel,
  // Empty: nothing picked yet, so the server's default (track, else setting) applies.
  cv_template: templates.cv || null,
  letter_template: templates.letter || null,
})

export const sendForApproval = (
  applicationId: string,
  templates: Record<RenderKind, string>,
  channel: SendChannel
) => preparePacket(applicationId, prepareBody(templates, channel))

/** A refusal to prepare, in plain words, with what to offer next (switches on `detail.code`). */
export const sendError = (e: unknown): Explained =>
  explainError(e, "Could not send for approval.")
