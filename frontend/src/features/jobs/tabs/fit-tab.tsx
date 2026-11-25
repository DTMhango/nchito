import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, CircleHelp, CircleX } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip, type ChipTone } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { ScoreRing } from "@/components/score-ring"
import {
  applicationQuery,
  assessmentsQuery,
  jobKeys,
  overrideAssessment,
  type AssessmentOut,
  type JobDetail,
} from "../api"

/** The assessment to show first: the conflict winner, else the highest score. */
export function pickAssessment(list: AssessmentOut[]): AssessmentOut | undefined {
  return (
    list.find((a) => a.is_conflict_winner) ??
    [...list].sort((x, y) => (y.score ?? -1) - (x.score ?? -1))[0]
  )
}

const FILTER = {
  pass: { icon: CircleCheck, cls: "text-good", text: "Passed" },
  fail: { icon: CircleX, cls: "text-danger", text: "Failed" },
  unknown: { icon: CircleHelp, cls: "text-warn", text: "Unknown" },
} as const

const STRENGTH: Record<string, { label: string; tone: ChipTone }> = {
  strong: { label: "Strong", tone: "good" },
  partial: { label: "Partial", tone: "warn" },
  gap: { label: "Gap", tone: "danger" },
}

export function FitTab({ job }: { job: JobDetail }) {
  const q = useQuery(assessmentsQuery(job.id))
  const app = useQuery(applicationQuery(job.application_id))
  const [chosen, setChosen] = useState<string | null>(null)
  const list = q.data ?? []
  const a = list.find((x) => x.id === chosen) ?? pickAssessment(list)

  if (q.isPending) return <p className="text-muted-foreground">Loading...</p>
  if (!a)
    return (
      <EmptyState
        title="Not scored yet"
        description="The score breakdown, filter results and requirement table appear here once this role has been assessed against a rubric."
      />
    )
  const matches = new Map(
    (app.data?.spec.requirement_match ?? []).map((m) => [m.requirement, m])
  )

  return (
    <div className="grid gap-7">
      <section aria-label="Score" className="flex flex-wrap items-center gap-4">
        <ScoreRing score={a.score ?? 0} size={88} label={a.score == null ? "Not scored" : undefined} />
        <div className="grid gap-1">
          <div className="text-lg font-semibold">
            {a.score == null ? "No score" : `Score ${a.score}`}
          </div>
          <div className="text-sm text-muted-foreground">
            Rubric <span className="num">v{a.rubric_version ?? "?"}</span>
            {a.model ? <> · scored by {a.model}</> : null}
          </div>
          {list.length > 1 && (
            <label className="flex items-center gap-2 text-sm">
              Campaign
              <select
                value={a.id}
                onChange={(e) => setChosen(e.target.value)}
                className="h-8 rounded-md border border-input bg-surface px-2 text-base field-focus"
              >
                {list.map((x, i) => (
                  <option key={x.id} value={x.id}>
                    Assessment {i + 1}
                    {x.score != null ? ` (score ${x.score})` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          {a.override && (
            <Chip tone="info">
              Overridden by {a.override.by}
              {a.override.score != null ? ` to ${a.override.score}` : ""}:{" "}
              {a.override.reason}
            </Chip>
          )}
        </div>
      </section>

      <section aria-label="Score breakdown" className="grid gap-2">
        <SectionHeader title="Score breakdown" />
        <ul className="panel p-4">
          {a.ratings.map((r) => (
            <li key={r.criterion} className="grid gap-1 border-t border-border row-pad first:border-t-0">
              <div className="flex items-baseline gap-3">
                <span className="font-semibold">{r.criterion}</span>
                <span className="num ml-auto" aria-label={`Rating ${r.rating} out of 5`}>
                  {r.rating} / 5
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-sunken" aria-hidden="true">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${(r.rating / 5) * 100}%` }}
                />
              </div>
              {r.note && <p className="text-sm text-muted-foreground">{r.note}</p>}
              {(r.evidence_fact_ids ?? []).length > 0 && (
                <p className="flex flex-wrap items-center gap-1 text-xs text-faint">
                  Evidence:
                  {(r.evidence_fact_ids ?? []).map((f) => (
                    <Chip key={f} tone="line" className="num">
                      {f}
                    </Chip>
                  ))}
                </p>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Filter results" className="grid gap-2">
        <SectionHeader title="Filter results" />
        {a.filter_results.length === 0 ? (
          <p className="text-sm text-muted-foreground">No filters ran.</p>
        ) : (
          <ul className="panel p-4">
            {a.filter_results.map((f) => {
              const o = FILTER[f.result]
              return (
                <li key={f.name} className="grid grid-cols-[18px_1fr] gap-2.5 border-t border-border row-pad first:border-t-0">
                  <o.icon className={`mt-0.5 size-[18px] ${o.cls}`} strokeWidth={1.5} aria-hidden="true" />
                  <div>
                    <span className="font-semibold">{f.name}</span>{" "}
                    <span className="sr-only">{o.text}.</span>
                    {!f.mandatory && <Chip tone="line">Optional</Chip>}
                    <div className="text-sm text-muted-foreground">{f.reason}</div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section aria-label="Requirements" className="grid gap-2">
        <SectionHeader title="Requirements" />
        {job.requirements.length === 0 ? (
          <p className="text-sm text-muted-foreground">No requirements were extracted.</p>
        ) : (
          <div className="overflow-x-auto panel">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-faint">
                  <th className="p-2.5 font-medium">Requirement</th>
                  <th className="p-2.5 font-medium">Kind</th>
                  <th className="p-2.5 font-medium">Your match</th>
                </tr>
              </thead>
              <tbody>
                {job.requirements.map((r) => {
                  const m = matches.get(r.text)
                  const s = m ? STRENGTH[m.strength] : null
                  return (
                    <tr key={r.text} className="border-t border-border align-top">
                      <td className="p-2.5">{r.text}</td>
                      <td className="p-2.5 capitalize">{r.kind}</td>
                      <td className="p-2.5">
                        {s ? <Chip tone={s.tone}>{s.label}</Chip> : <span className="text-faint">Not matched yet</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <OverrideForm assessment={a} jobId={job.id} />
    </div>
  )
}

function OverrideForm({ assessment, jobId }: { assessment: AssessmentOut; jobId: string }) {
  const qc = useQueryClient()
  const [score, setScore] = useState("")
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const m = useMutation({
    mutationFn: () =>
      overrideAssessment(assessment.id, score.trim() === "" ? null : Number(score), reason.trim()),
    onSuccess: () => {
      setScore("")
      setReason("")
      toast.success("Override recorded")
      void qc.invalidateQueries({ queryKey: jobKeys.assessments(jobId) })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Could not save."),
  })
  return (
    <section aria-label="Override" className="grid gap-2">
      <SectionHeader title="Override the score" aside="Needs a reason; it goes in the activity log" />
      <form
        className="grid max-w-[460px] gap-3 panel p-4"
        onSubmit={(e) => {
          e.preventDefault()
          const n = score.trim() === "" ? null : Number(score)
          if (n !== null && (!Number.isInteger(n) || n < 0 || n > 100))
            return setError("Use a whole number from 0 to 100, or leave it empty.")
          if (reason.trim().length < 3) return setError("Say why you are overriding.")
          setError(null)
          m.mutate()
        }}
      >
        <label className="grid gap-1 text-sm">
          New score (optional)
          <Input inputMode="numeric" value={score} onChange={(e) => setScore(e.target.value)} className="num max-w-[120px]" />
        </label>
        <label className="grid gap-1 text-sm">
          Reason
          <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <Button type="submit" size="sm" className="justify-self-start" disabled={m.isPending}>
          Record override
        </Button>
      </form>
    </section>
  )
}
