import { useQuery } from "@tanstack/react-query"
import { Bot } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import { settingsQuery } from "../api"
import type { ImportSource } from "./api"

/** Old-kit files the built-in parser cannot read go to the AI provider only while this is on. */
export const OLD_KIT_AI_KEY = "data.old_kit_ai_extraction"

/**
 * Whether an upload of this kind may be sent to the AI provider. Free-form text always is; an
 * old folder is when the setting is on. A setting that has not loaded counts as on, so the
 * owner is warned rather than surprised (unknown is not no-risk).
 */
export function useSendsToAi(source: ImportSource): boolean {
  const q = useQuery(settingsQuery())
  if (source === "free_form") return true
  if (source !== "old_kit_zip") return false
  const v = (q.data ?? [])
    .flatMap((g) => g.settings)
    .find((s) => s.key === OLD_KIT_AI_KEY)?.value
  return v !== false
}

/** Shown before the upload, with a box the owner must tick before the file can be sent. */
export function AiNotice({
  source,
  acknowledged,
  onAcknowledge,
}: {
  source: ImportSource
  acknowledged: boolean
  onAcknowledge: (v: boolean) => void
}) {
  return (
    <div
      role="note"
      aria-label="AI provider notice"
      className="grid gap-2 rounded-sm border border-warn bg-warn-soft p-3 text-warn"
    >
      <p className="flex items-start gap-2">
        <Bot className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>
          {source === "free_form"
            ? "This text will be sent to your AI provider so it can propose facts."
            : "Files the built-in reader does not recognise will be sent to your AI provider so it can propose facts."}{" "}
          It is sent as data, and everything that comes back arrives
          unconfirmed.
          {source === "old_kit_zip" &&
            " Turn off the AI setting under Data to use the built-in reader only."}
        </span>
      </p>
      <label className="flex items-center gap-2 font-medium">
        <Checkbox
          checked={acknowledged}
          onCheckedChange={(v) => onAcknowledge(v === true)}
        />
        I understand this will be sent to my AI provider
      </label>
    </div>
  )
}
