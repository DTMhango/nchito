import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { SubNav } from "@/components/sub-nav"
import { cn } from "@/lib/utils"
import {
  activatePrompt,
  aiKeys,
  promptsQuery,
  savePrompt,
  stageLabel,
  type Prompt,
} from "./api"
import { lineDiff } from "./line-diff"

/** Versioned prompts per stage: history, diff against the active version, save and activate. */
export function PromptsSection() {
  const { data = [] } = useQuery(promptsQuery())
  const stages = [...new Set(data.map((p) => p.stage))]
  const [picked, setPicked] = useState<string | null>(null)
  const stage = picked ?? stages[0]
  const versions = data.filter((p) => p.stage === stage)
  return (
    <section aria-labelledby="ai-prompts" className="grid gap-3">
      <SectionHeader
        title={<span id="ai-prompts">Prompts</span>}
        aside="Each save is a new version. Changes apply to future work only."
      />
      <SubNav label="Prompt stages">
        {stages.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={s === stage}
            onClick={() => setPicked(s)}
            className={cn(
              "rounded-full px-3 py-1 text-sm",
              s === stage
                ? "bg-primary-soft text-primary-ink"
                : "text-muted-foreground"
            )}
          >
            {stageLabel(s)}
          </button>
        ))}
      </SubNav>
      {stage && <StagePrompts key={stage} stage={stage} versions={versions} />}
    </section>
  )
}

function StagePrompts({
  stage,
  versions,
}: {
  stage: string
  versions: Prompt[]
}) {
  const queryClient = useQueryClient()
  const active = versions.find((v) => v.active)
  const [selectedId, setSelectedId] = useState<string | undefined>(active?.id)
  const selected =
    versions.find((v) => v.id === selectedId) ?? active ?? versions[0]
  const [draft, setDraft] = useState(selected?.text ?? "")
  const [note, setNote] = useState("")
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: aiKeys.prompts })
  const save = useMutation({
    mutationFn: () => savePrompt(stage, draft, note || undefined),
    onSuccess: (p) => {
      toast.success(`Saved as version ${p.version}. Activate it to use it.`)
      setSelectedId(p.id)
      setNote("")
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const activate = useMutation({
    mutationFn: activatePrompt,
    onSuccess: (p) => {
      toast.success(`${stageLabel(p.stage)} now uses version ${p.version}.`)
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const diff = useMemo(
    () =>
      selected && active && selected.id !== active.id
        ? lineDiff(active.text, selected.text)
        : null,
    [selected, active]
  )
  return (
    <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
      <ol
        className="grid content-start gap-1"
        aria-label={`${stageLabel(stage)} versions`}
      >
        {versions.map((v) => (
          <li key={v.id}>
            <button
              type="button"
              aria-current={v.id === selected?.id ? "true" : undefined}
              onClick={() => {
                setSelectedId(v.id)
                setDraft(v.text)
              }}
              className={cn(
                "flex w-full flex-wrap items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                v.id === selected?.id ? "bg-surface-2" : "hover:bg-sunken"
              )}
            >
              <span className="num font-semibold">v{v.version}</span>
              {v.active && <Chip tone="good">Active</Chip>}
              <span className="truncate text-faint">{v.note}</span>
            </button>
          </li>
        ))}
      </ol>
      <div className="grid min-w-0 gap-3">
        {diff && (
          <div
            aria-label="Changes from the active version"
            className="grid gap-1"
          >
            <span className="eyebrow">
              v{active?.version} (active) → v{selected?.version}
            </span>
            <pre className="max-h-56 overflow-auto rounded-md bg-sunken p-2.5 num text-xs whitespace-pre-wrap">
              {diff.map((d, i) => (
                <div
                  key={i}
                  className={cn(
                    d.kind === "add" && "bg-good-soft text-good",
                    d.kind === "del" &&
                      "bg-danger-soft text-danger line-through"
                  )}
                >
                  {d.kind === "add" ? "+ " : d.kind === "del" ? "- " : "  "}
                  {d.text}
                </div>
              ))}
            </pre>
          </div>
        )}
        <div className="grid gap-1.5">
          <Label htmlFor={`prompt-${stage}`}>Prompt text</Label>
          <Textarea
            id={`prompt-${stage}`}
            rows={9}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid min-w-[200px] flex-1 gap-1.5">
            <Label htmlFor={`prompt-note-${stage}`}>Note</Label>
            <Input
              id={`prompt-note-${stage}`}
              value={note}
              placeholder="What changed"
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <Button
            variant="outline"
            disabled={
              save.isPending || !draft.trim() || draft === selected?.text
            }
            onClick={() => save.mutate()}
          >
            Save new version
          </Button>
          {selected && !selected.active && (
            <Button
              disabled={activate.isPending}
              onClick={() => activate.mutate(selected.id)}
            >
              Activate v{selected.version}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
