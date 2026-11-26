import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { PauseCircle, RotateCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { formatCost } from "@/lib/cost"
import type { FactIndex } from "@/features/studio/draft"
import { packKeys, practiceQuery, practise, retryPractice } from "./api"
import { ClaimView } from "./claim-view"
import type { LikelyQuestion, PracticeFeedback, PracticeOut } from "./shapes"

function Attempt({
  row,
  index,
  currency,
  onRetry,
  retrying,
}: {
  row: PracticeOut
  index: FactIndex
  currency: string | undefined
  onRetry: () => void
  retrying: boolean
}) {
  const fb = row.feedback as PracticeFeedback | null
  return (
    <li
      data-practice={row.id}
      data-status={row.status}
      className="grid gap-1.5 rounded-md border border-border bg-surface p-3 text-sm"
    >
      <p className="font-semibold">{row.question}</p>
      <p className="whitespace-pre-wrap text-muted-foreground">
        {row.draft_answer}
      </p>
      {row.status === "done" && fb && (
        <div aria-live="polite" className="grid gap-1.5">
          <p>{fb.feedback}</p>
          {fb.strengths.length > 0 && (
            <span className="flex flex-wrap gap-1">
              {fb.strengths.map((s) => (
                <Chip key={s} tone="good">
                  {s}
                </Chip>
              ))}
            </span>
          )}
          {fb.improve.length > 0 && (
            <span className="flex flex-wrap gap-1">
              {fb.improve.map((s) => (
                <Chip key={s} tone="warn">
                  {s}
                </Chip>
              ))}
            </span>
          )}
          {fb.suggested_answer && (
            <ul className="m-0 grid list-none p-0">
              <ClaimView
                id={`practice.${row.id}`}
                claim={fb.suggested_answer}
                index={index}
                lead="A stronger answer from your facts"
              />
            </ul>
          )}
          {row.cost_micros > 0 && (
            <span className="text-xs text-faint">
              Cost {formatCost(row.cost_micros, { currency })}
            </span>
          )}
        </div>
      )}
      {row.status !== "done" && (
        <div role="alert" className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 font-semibold text-warn">
            <PauseCircle className="size-4" aria-hidden="true" />
            {row.status === "paused"
              ? "Paused: the AI budget is used up"
              : `No feedback: ${row.error ?? "the request failed"}`}
          </span>
          <Button
            size="xs"
            variant="outline"
            disabled={retrying}
            onClick={onRetry}
          >
            <RotateCw aria-hidden="true" />
            Retry
          </Button>
        </div>
      )}
    </li>
  )
}

/** Practice mode: pick a likely question, write your answer, get feedback against your facts. */
export function PracticePanel({
  jobId,
  questions,
  index,
  currency,
}: {
  jobId: string
  questions: LikelyQuestion[]
  index: FactIndex
  /** Currency of the AI budget, for the cost line (from the pack estimate). */
  currency?: string
}) {
  const qc = useQueryClient()
  const [qi, setQi] = useState(0)
  const [draft, setDraft] = useState("")
  const history = useQuery(practiceQuery(jobId))
  const refresh = () =>
    qc.invalidateQueries({ queryKey: packKeys.practice(jobId) })
  const run = useMutation({
    mutationFn: () => {
      const q = questions[qi]
      return practise(jobId, {
        question: q.question,
        category: q.category,
        draft_answer: draft,
      })
    },
    onSuccess: () => {
      setDraft("")
      return refresh()
    },
  })
  const retry = useMutation({
    mutationFn: (id: string) => retryPractice(id),
    onSuccess: refresh,
  })

  if (!questions.length)
    return (
      <p className="text-sm text-muted-foreground">
        Practice needs the likely questions section. Generate it first.
      </p>
    )
  return (
    <div role="region" aria-label="Practice" className="grid gap-2.5 panel p-4">
      <label className="grid gap-1 text-sm font-semibold">
        Question
        <select
          value={qi}
          onChange={(e) => {
            setQi(Number(e.target.value))
            run.reset()
          }}
          className="h-9 rounded-md border border-border bg-transparent px-2 font-normal"
        >
          {questions.map((q, i) => (
            <option key={q.question} value={i}>
              {q.question}
            </option>
          ))}
        </select>
      </label>
      <label className="grid gap-1 text-sm font-semibold">
        Your answer
        <Textarea
          rows={5}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="font-normal"
          placeholder="Answer as you would in the room."
        />
      </label>
      <Button
        size="sm"
        className="justify-self-start"
        disabled={!draft.trim() || run.isPending}
        onClick={() => run.mutate()}
      >
        {run.isPending ? "Reading your answer..." : "Get feedback"}
      </Button>
      {run.isError && (
        <p role="alert" className="text-sm text-danger">
          {run.error.message}
        </p>
      )}
      {retry.isError && (
        <p role="alert" className="text-sm text-danger">
          {retry.error.message}
        </p>
      )}
      {history.data && history.data.length > 0 && (
        <ol
          aria-label="Your practice answers"
          className="m-0 grid list-none gap-2 p-0"
        >
          {history.data.map((row) => (
            <Attempt
              key={row.id}
              row={row}
              index={index}
              currency={currency}
              retrying={retry.isPending}
              onRetry={() => retry.mutate(row.id)}
            />
          ))}
        </ol>
      )}
    </div>
  )
}
