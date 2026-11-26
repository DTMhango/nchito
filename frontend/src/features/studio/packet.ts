/**
 * "Send for approval": render the checked CV and letter, then build the packet from them
 * (`POST /applications/{id}/packet`). The server refuses (409) a packet whose files do not come
 * from the latest checked, non-blocking spec version, so nothing here decides that on its own.
 */
import type { Schemas } from "@/lib/api/types"
import { isApiError } from "@/lib/api/client"
import {
  buildPacket,
  renderDocuments,
  type DocumentOut,
  type DraftAnswer,
  type PacketBuildIn,
  type PacketFile,
  type RenderKind,
} from "./api"

type Connection = Schemas["ConnectionOut"]
const MAILBOXES = new Set<Connection["provider"]>(["gmail", "imap_smtp"])

/** The address the connected mailbox sends as, else the owner's own address. */
export function sendingIdentity(
  connections: Connection[],
  ownerEmail: string | undefined
): string | null {
  for (const c of connections) {
    if (!c.enabled || !MAILBOXES.has(c.provider)) continue
    const from = c.config.from_address
    if (typeof from === "string" && from.trim()) return from.trim()
  }
  return ownerEmail?.trim() || null
}

/** Only answers with a value travel; ask_owner and do_not_answer stay out (unknown is not yes). */
export const packetAnswers = (answers: DraftAnswer[]) =>
  answers
    .filter((a) => a.outcome === "value")
    .map((a) =>
      a.answer_id
        ? { question: a.question, answer_id: a.answer_id }
        : { question: a.question, value: a.value }
    )

const FILE_NAME: Record<RenderKind, string> = {
  cv: "CV.pdf",
  letter: "Cover_letter.pdf",
}

const asFile = (kind: RenderKind, doc: DocumentOut): PacketFile => ({
  name: FILE_NAME[kind],
  kind,
  sha256: doc.content_hash,
  document_id: doc.id,
})

async function renderPdf(
  id: string,
  kind: RenderKind,
  template: string
): Promise<PacketFile> {
  const out = await renderDocuments(id, {
    kind,
    template_key: template,
    formats: ["pdf"],
  })
  const pdf = out.documents.find((d) => d.kind === kind && d.fmt === "pdf")
  if (!pdf)
    throw new Error(`The ${kind === "cv" ? "CV" : "letter"} did not render.`)
  return asFile(kind, pdf)
}

export type SendInput = {
  applicationId: string
  applyUrl: string | null
  identity: string
  answers: DraftAnswer[]
  templates: Record<RenderKind, string>
}

/** Render both documents and build the packet (manual hand-off to the posting's link). */
export async function sendForApproval(input: SendInput) {
  const files = [
    await renderPdf(input.applicationId, "cv", input.templates.cv),
    await renderPdf(input.applicationId, "letter", input.templates.letter),
  ]
  const body: PacketBuildIn = {
    channel: "manual",
    destination_url: input.applyUrl,
    sending_identity: input.identity,
    answers: packetAnswers(input.answers),
    files,
  }
  return buildPacket(input.applicationId, body)
}

/** A refusal in plain words: stale or blocking checks, or the application already went out. */
export function sendError(e: unknown): { text: string; recheck: boolean } {
  if (isApiError(e, 409)) {
    const detail = typeof e.body?.detail === "string" ? e.body.detail : ""
    if (/cannot be repacked|gone out|submitted|applying/i.test(detail))
      return {
        text: "This application has already gone out, so its packet can no longer change.",
        recheck: false,
      }
    return {
      text: `The checks are out of date or something blocks sending${detail ? ` (${detail})` : ""}. Re-run the checks, fix what blocks, then send again.`,
      recheck: true,
    }
  }
  return {
    text: e instanceof Error ? e.message : "Could not send for approval.",
    recheck: false,
  }
}
