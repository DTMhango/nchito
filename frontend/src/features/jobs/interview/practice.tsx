import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { FactTag } from "@/components/fact-tag"
import { indexFacts } from "@/features/studio/draft"
import type { FactOut } from "@/features/studio/api"
import type { PackItem } from "../w3-pending-types"
import { practice } from "./api"

/** Practice mode: pick a likely question, write your answer, get feedback against your facts. */
export function PracticePanel({
  appId,
  questions,
  facts,
}: {
  appId: string
  questions: PackItem[]
  facts: FactOut[]
}) {
  const [qid, setQid] = useState(questions[0]?.id ?? "")
  const [draft, setDraft] = useState("")
  const run = useMutation({
    mutationFn: () => practice(appId, { question_id: qid, draft }),
  })
  const index = indexFacts(facts)
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
          value={qid}
          onChange={(e) => {
            setQid(e.target.value)
            run.reset()
          }}
          className="h-9 rounded-md border border-border bg-transparent px-2 font-normal"
        >
          {questions.map((q) => (
            <option key={q.id} value={q.id}>
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
      {run.data && (
        <div aria-live="polite" className="grid gap-1.5 text-sm">
          <p>{run.data.feedback}</p>
          <span className="flex flex-wrap items-center gap-1.5">
            {run.data.fact_ids.map((id) => {
              const f = index.get(id)
              return f ? (
                <FactTag
                  key={id}
                  code={f.code}
                  text={f.text}
                  status={f.status as "approved" | "draft" | "retired"}
                />
              ) : null
            })}
            {run.data.gaps.map((g) => (
              <Chip key={g} tone="warn">
                {g}
              </Chip>
            ))}
          </span>
        </div>
      )}
    </div>
  )
}
