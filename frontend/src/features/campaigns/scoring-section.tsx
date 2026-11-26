import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { ThresholdTrack, type Thresholds } from "@/components/threshold-track"
import { facetsQuery, jobsQuery, rubricsQuery, useRubricMutations } from "./api"
import { BacktestPanel } from "./backtest-panel"
import { NativeSelect } from "./bits"
import { RubricEditor } from "./rubric-editor"
import { rubricProblems } from "./rubric"
import { useAutosave } from "./use-autosave"
import type { Rubric, RubricBody } from "./types"

type Props = {
  campaignId: string
  rubricId: string | null
  /** General thresholds from Settings, used where the rubric sets none. */
  defaults: Thresholds
  onRubricChange: (id: string) => void
}

export function ScoringSection({
  campaignId,
  rubricId,
  defaults,
  onRubricChange,
}: Props) {
  const rubrics = useQuery(rubricsQuery())
  const m = useRubricMutations()
  const all = useMemo(() => rubrics.data ?? [], [rubrics.data])
  const current = all.find((r) => r.id === rubricId)
  const family = current?.family
  const versions = useMemo(
    () =>
      all
        .filter((r) => (family ? r.family === family : false))
        .sort((a, b) => b.version - a.version),
    [all, family]
  )
  const [chosen, setChosen] = useState<string | null>(null)
  const draft = versions.find((v) => v.status === "draft")
  const shown =
    versions.find((v) => v.id === chosen) ?? draft ?? current ?? null

  const startDraft = async (from: Rubric) => {
    try {
      const r = await m.create.mutateAsync({
        name: from.name,
        body: structuredClone(from.body) as RubricBody,
      })
      setChosen(r.id)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not start a draft.")
    }
  }

  if (rubrics.isLoading)
    return <p className="text-muted-foreground">Loading the rubric...</p>

  if (!shown) {
    return (
      <div className="grid justify-items-start gap-2">
        <p className="text-muted-foreground">
          This campaign has no rubric yet. Without one, roles are not scored.
        </p>
        <Button
          type="button"
          variant="outline"
          disabled={m.create.isPending}
          onClick={async () => {
            const r = await m.create.mutateAsync({
              name: "New rubric",
              body: { criteria: [], penalties: [] },
            })
            onRubricChange(r.id)
            setChosen(r.id)
          }}
        >
          Create a rubric
        </Button>
      </div>
    )
  }

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">Version</span>
          <NativeSelect
            value={shown.id}
            onChange={(e) => setChosen(e.target.value)}
            className="w-56"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version} ({v.status})
              </option>
            ))}
          </NativeSelect>
        </label>
        <Chip tone={shown.status === "draft" ? "info" : "good"}>
          {shown.status === "draft"
            ? "Draft: not used for scoring yet"
            : shown.status === "active"
              ? "Active: used for scoring now"
              : "Retired"}
        </Chip>
        {shown.status !== "draft" && !draft && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={m.create.isPending}
            onClick={() => void startDraft(shown)}
          >
            Start a new draft from this version
          </Button>
        )}
      </div>

      <RubricBlock
        key={shown.id}
        rubric={shown}
        campaignId={campaignId}
        defaults={defaults}
        onActivated={(r) => onRubricChange(r.id)}
      />
    </div>
  )
}

function RubricBlock({
  rubric,
  campaignId,
  defaults,
  onActivated,
}: {
  rubric: Rubric
  campaignId: string
  defaults: Thresholds
  onActivated: (r: Rubric) => void
}) {
  const m = useRubricMutations()
  const catalogue = useQuery(facetsQuery()).data ?? []
  const jobs = useQuery(jobsQuery()).data ?? []
  const readOnly = rubric.status !== "draft"
  const [body, setBody] = useState<RubricBody>(
    () => rubric.body as unknown as RubricBody
  )
  const auto = useAutosave<RubricBody>(
    (b) => m.update.mutateAsync({ id: rubric.id, name: rubric.name, body: b }),
    800
  )
  const edit = (next: RubricBody) => {
    setBody(next)
    auto.touch(next)
  }

  const t = body.thresholds ?? {}
  const value: Thresholds = {
    shortlist: t.shortlist ?? defaults.shortlist,
    tailor: t.tailor ?? defaults.tailor,
    auto: t.auto_apply ?? defaults.auto,
  }
  const problems = rubricProblems(body)
  const scores = jobs.flatMap((j) =>
    j.best_score == null ? [] : [j.best_score]
  )

  return (
    <div className="grid gap-6">
      <RubricEditor
        body={body}
        onChange={edit}
        readOnly={readOnly}
        catalogue={catalogue}
      />

      <div className="grid gap-2">
        <h4 className="text-md">Thresholds</h4>
        <p className="text-sm text-muted-foreground">
          The score a role needs to be shortlisted, to have documents prepared,
          and to be applied to without asking. The bars show your saved roles.
        </p>
        <ThresholdTrack
          scores={scores}
          value={value}
          onValueChange={(v) =>
            !readOnly &&
            edit({
              ...body,
              thresholds: {
                shortlist: v.shortlist,
                tailor: v.tailor,
                auto_apply: v.auto,
              },
            })
          }
          summary={(v, c) => (
            <>
              At these settings {c.shortlist} of {scores.length} saved roles are
              shortlisted, {c.tailor} get documents prepared and {c.auto} could
              be applied to automatically ({v.auto} or more).
            </>
          )}
        />
        {readOnly && (
          <p className="text-sm text-muted-foreground">
            This version is locked. Start a new draft to change it.
          </p>
        )}
      </div>

      {!readOnly && (
        <BacktestPanel
          jobs={jobs}
          disabledReason={
            problems.length > 0
              ? "Fix the problems above before testing."
              : null
          }
          estimating={m.estimate.isPending}
          estimate={m.estimate.data ?? null}
          onEstimate={async (jobIds) => {
            await auto.flush()
            m.backtest.reset()
            m.estimate.mutate({
              rubric_id: rubric.id,
              campaign_id: campaignId,
              job_ids: jobIds,
            })
          }}
          running={m.backtest.isPending}
          result={m.backtest.data ?? null}
          error={m.estimate.error?.message ?? m.backtest.error?.message ?? null}
          canActivate={problems.length === 0}
          activating={m.activate.isPending}
          onRun={async (jobIds) => {
            await auto.flush()
            m.backtest.mutate({
              rubric_id: rubric.id,
              campaign_id: campaignId,
              job_ids: jobIds,
            })
          }}
          onActivate={async () => {
            await auto.flush()
            try {
              const r = await m.activate.mutateAsync(rubric.id)
              onActivated(r)
              toast.success("This rubric is now active.")
            } catch (e) {
              toast.error(
                e instanceof Error ? e.message : "Could not activate."
              )
            }
          }}
        />
      )}
      {!readOnly && auto.state === "error" && (
        <p className="text-sm text-danger" role="alert">
          The draft was not saved: {auto.error}
        </p>
      )}
    </div>
  )
}
