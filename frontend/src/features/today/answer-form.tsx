import { useId, useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { unwrap } from "@/lib/api/client"
import {
  gen,
  type AnswerScope,
  type PendingAction,
} from "@/features/applications/api"
import { readDetail, SCOPE_OPTIONS } from "./decisions"

const SCOPES = SCOPE_OPTIONS.map((o) => o.value)
const isScope = (v: unknown): v is AnswerScope =>
  typeof v === "string" && (SCOPES as string[]).includes(v)

/**
 * The default scope comes from the answers settings (DESIGN 5.4): one for routine questions,
 * one for material ones. Nothing is assumed in code; until the setting loads, or if it can't,
 * nothing is pre-selected and the server applies the same setting on save.
 */
export function useDefaultScope(material: boolean) {
  const key = material
    ? "answers.material_default_scope"
    : "answers.routine_default_scope"
  const q = useQuery({
    queryKey: ["settings", key],
    queryFn: () =>
      unwrap(gen.GET("/api/settings/{key}", { params: { path: { key } } })),
    staleTime: 5 * 60_000,
    retry: false,
  })
  const v = q.data?.value
  return { scope: isScope(v) ? v : null, loading: q.isPending }
}

export type AnswerSubmit = { answer: string; scope: AnswerScope | null }

/** Inline answer to a new question, with the scope choice shown before saving. */
export function AnswerForm({
  action,
  affected,
  busy,
  onSubmit,
  onCancel,
}: {
  action: PendingAction
  /** Roles this one answer settles. */
  affected: string[]
  busy: boolean
  onSubmit: (v: AnswerSubmit) => void
  onCancel: () => void
}) {
  const detail = readDetail(action)
  const material = detail.material === true
  const def = useDefaultScope(material)
  const [answer, setAnswer] = useState("")
  const [picked, setPicked] = useState<AnswerScope | null>(null)
  const scope = picked ?? def.scope
  const id = useId()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (answer.trim()) onSubmit({ answer: answer.trim(), scope })
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Answer the question"
      className="grid w-full gap-3 rounded-sm border border-border bg-sunken p-3"
    >
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-a`} className="font-semibold">
          {detail.question ?? action.title}
        </Label>
        {detail.options?.length ? (
          <Select value={answer} onValueChange={setAnswer}>
            <SelectTrigger id={`${id}-a`} className="w-full bg-surface">
              <SelectValue placeholder="Choose an answer" />
            </SelectTrigger>
            <SelectContent>
              {detail.options.map((o) => (
                <SelectItem key={o} value={o}>
                  {o}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            id={`${id}-a`}
            className="bg-surface"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
          />
        )}
      </div>

      <fieldset className="grid gap-1.5">
        <legend className="mb-1 text-sm font-semibold">
          Use this answer for
          <span className="ml-2 font-normal text-faint">
            {material
              ? "Material question: kept narrow by default."
              : "Routine question."}
          </span>
        </legend>
        <RadioGroup
          value={scope ?? ""}
          onValueChange={(v) => setPicked(v as AnswerScope)}
          aria-label="Answer scope"
          className="grid gap-1.5 sm:grid-cols-2"
        >
          {SCOPE_OPTIONS.map((o) => (
            <Label
              key={o.value}
              htmlFor={`${id}-${o.value}`}
              className="flex cursor-pointer items-start gap-2 rounded-sm border border-border bg-surface p-2 has-data-[state=checked]:border-primary has-data-[state=checked]:bg-primary-soft"
            >
              <RadioGroupItem id={`${id}-${o.value}`} value={o.value} />
              <span className="grid">
                <span className="font-medium">{o.label}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  {o.hint}
                </span>
              </span>
            </Label>
          ))}
        </RadioGroup>
        {!scope && !def.loading && (
          <span className="text-xs text-faint">
            Nothing chosen: your default scope setting applies when you save.
          </span>
        )}
      </fieldset>

      {affected.length > 1 && (
        <p className="text-sm text-muted-foreground">
          Settles {affected.length} applications: {affected.join(", ")}.
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={busy || !answer.trim()}>
          Save answer
        </Button>
      </div>
    </form>
  )
}
