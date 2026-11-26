import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { ck, rubricsQuery, useRubricMutations } from "@/features/campaigns/api"
import type { RubricBody } from "@/features/campaigns/types"
import { PolicyPreview } from "@/features/campaigns/preview/policy-preview"
import { pk, type PreviewThresholds } from "@/features/campaigns/preview/api"
import { apKeys, putSetting, type CampaignOut, type SettingOut } from "./api"

/** The settings a policy preview may take as unsaved edits (caps and quiet hours). */
export const PREVIEW_SETTING_KEYS = [
  "automation.daily_cap",
  "automation.weekly_cap",
  "automation.quiet_hours_start",
  "automation.quiet_hours_end",
] as const

/** Unsaved limit edits as preview `settings`: numbers for the caps, text for the times. */
export function previewSettings(
  drafts: Record<string, string>,
  settings: Record<string, SettingOut> | undefined
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const key of PREVIEW_SETTING_KEYS) {
    const raw = drafts[key]
    if (raw === undefined || raw.trim() === "") continue
    const kind = settings?.[key]?.kind
    if (kind === "int" || kind === "float") {
      const n = Number(raw)
      if (Number.isFinite(n)) out[key] = n
    } else out[key] = raw.trim()
  }
  return out
}

/**
 * The score histogram with the tailor and auto-apply handles for one campaign, and "Save thresholds".
 * A rubric with its own lines is saved as a new rubric version (update, then activate);
 * otherwise the shared settings are saved.
 */
export function PolicyThresholds({
  campaign,
  settings,
  current,
}: {
  campaign: CampaignOut
  settings: Record<string, unknown>
  current: Record<string, SettingOut> | undefined
}) {
  const qc = useQueryClient()
  const rubrics = useQuery(rubricsQuery())
  const rm = useRubricMutations()
  const [pending, setPending] = useState<PreviewThresholds | null>(null)
  const [round, setRound] = useState(0)
  const rubric = rubrics.data?.find((r) => r.id === campaign.rubric_id)
  const own = rubric?.body.thresholds
  const ownLines = own != null && (own.tailor != null || own.auto_apply != null)

  const save = useMutation({
    mutationFn: async (t: PreviewThresholds) => {
      if (rubric && ownLines) {
        const body = structuredClone(rubric.body) as unknown as RubricBody
        body.thresholds = {
          ...body.thresholds,
          tailor: t.tailor,
          auto_apply: t.auto_apply,
        }
        const draft = await rm.update.mutateAsync({
          id: rubric.id,
          name: rubric.name,
          body,
        })
        const active = await rm.activate.mutateAsync(draft.id)
        return `Rubric version ${active.version} is now active with these lines.`
      }
      const auto = Number(current?.["scoring.threshold_auto_apply"]?.value)
      // Keep the pair valid at every step: raise auto-apply first when tailor goes above it.
      const order: [string, number][] =
        Number.isFinite(auto) && t.tailor > auto
          ? [
              ["scoring.threshold_auto_apply", t.auto_apply],
              ["scoring.threshold_tailor", t.tailor],
            ]
          : [
              ["scoring.threshold_tailor", t.tailor],
              ["scoring.threshold_auto_apply", t.auto_apply],
            ]
      for (const [key, value] of order) await putSetting(key, value)
      return "Score lines saved for every campaign."
    },
    onSuccess: (msg) => {
      setPending(null)
      setRound((r) => r + 1)
      void qc.invalidateQueries({ queryKey: apKeys.settings })
      void qc.invalidateQueries({ queryKey: apKeys.campaigns })
      void qc.invalidateQueries({ queryKey: ck.settings })
      void qc.invalidateQueries({ queryKey: [pk.previewRoot] })
      toast.success(msg)
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <div className="grid gap-2">
      <h4 className="text-md">Score lines</h4>
      <p className="text-sm text-muted-foreground">
        {ownLines
          ? "This campaign's rubric sets its own lines. Saving makes a new rubric version."
          : "These lines are shared by every campaign whose rubric sets none."}
      </p>
      <PolicyPreview
        key={round}
        campaignId={campaign.id}
        automation={campaign.automation}
        settings={settings}
        onThresholdsChange={setPending}
      />
      {pending && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            disabled={save.isPending}
            onClick={() => save.mutate(pending)}
          >
            Save thresholds
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={save.isPending}
            onClick={() => {
              setPending(null)
              setRound((r) => r + 1)
            }}
          >
            Undo
          </Button>
        </div>
      )}
    </div>
  )
}
