import { useState } from "react"
import { Pencil } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { FactTag } from "@/components/fact-tag"
import { cn } from "@/lib/utils"
import {
  useFactAction,
  useRemove,
  useSave,
  type ExperienceOut,
  type FactIn,
  type FactOut,
} from "./api"
import {
  ConfirmButton,
  errorText,
  Field,
  FormDialog,
  NativeSelect,
  NeedsReviewChip,
  PillToggle,
  ReviewActions,
} from "./common"
import { csv, FACT_KINDS, FACT_STATUS, parseCsv } from "./labels"

const toIn = (f: FactOut): FactIn => ({
  code: f.code,
  kind: f.kind,
  text: f.text,
  canonical_wording: f.canonical_wording,
  experience_id: f.experience_id,
  tags: f.tags,
  tracks: f.tracks,
  keep_out_of_prompts: f.keep_out_of_prompts,
  confidence_note: f.confidence_note,
})

const STATUS_TONE = {
  approved: "good",
  draft: "warn",
  retired: "line",
} as const

/**
 * One fact. Click the text (or focus it and press Enter) to edit in place; Ctrl+Enter saves,
 * Escape cancels. The two switches save immediately. Everything else is in the Edit dialog.
 */
export function FactRow({
  fact,
  onEdit,
}: {
  fact: FactOut
  onEdit: (f: FactOut) => void
}) {
  const save = useSave<FactOut, FactIn>("facts")
  const act = useFactAction()
  const remove = useRemove("facts")
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(fact.text)

  const patch = (p: Partial<FactIn>, done?: () => void) =>
    save.mutate(
      { id: fact.id, body: { ...toIn(fact), ...p } },
      { onSuccess: done, onError: (e) => toast.error(errorText(e)) }
    )
  const commit = () => {
    const text = draft.trim()
    if (!text || text === fact.text) return setEditing(false)
    patch({ text }, () => setEditing(false))
  }

  return (
    <li
      data-testid={`fact-${fact.code}`}
      className={cn(
        "grid gap-1.5 border-t border-border px-3 py-2.5 first:border-t-0",
        fact.status === "retired" && "opacity-70"
      )}
    >
      <div className="flex items-start gap-2.5">
        <FactTag
          code={fact.code}
          text={fact.text}
          status={fact.status}
          className="mt-0.5 shrink-0"
        />
        {editing ? (
          <div className="grid flex-1 gap-1.5">
            <Textarea
              autoFocus
              aria-label={`Text of ${fact.code}`}
              value={draft}
              rows={2}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setDraft(fact.text)
                  setEditing(false)
                } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault()
                  commit()
                }
              }}
            />
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Button size="xs" onClick={commit} disabled={save.isPending}>
                Save
              </Button>
              <Button
                size="xs"
                variant="ghost"
                onClick={() => {
                  setDraft(fact.text)
                  setEditing(false)
                }}
              >
                Cancel
              </Button>
              <span>Ctrl+Enter saves, Esc cancels</span>
            </div>
          </div>
        ) : (
          <button
            type="button"
            aria-label={`Edit text of ${fact.code}`}
            title="Click to edit"
            onClick={() => {
              setDraft(fact.text)
              setEditing(true)
            }}
            className="min-w-0 flex-1 rounded-sm text-left leading-snug hover:bg-sunken focus-visible:outline-2 focus-visible:outline-primary-ink"
          >
            {fact.text}
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 pl-0 sm:pl-[3.4rem]">
        <Chip>{FACT_KINDS[fact.kind]}</Chip>
        <Chip tone={STATUS_TONE[fact.status]}>{FACT_STATUS[fact.status]}</Chip>
        {fact.review_state === "needs_review" && <NeedsReviewChip />}
        {(fact.tracks ?? []).map((t) => (
          <Chip key={`t-${t}`} tone="primary" title="Track">
            {t}
          </Chip>
        ))}
        {(fact.tags ?? []).map((t) => (
          <Chip key={`g-${t}`} tone="line">
            #{t}
          </Chip>
        ))}
        <span className="mx-1 hidden h-4 w-px bg-border sm:block" />
        <PillToggle
          pressed={!!fact.canonical_wording}
          onPressedChange={(v) => patch({ canonical_wording: v })}
          title="Figures and units must appear exactly as written"
        >
          Exact wording
        </PillToggle>
        <PillToggle
          pressed={!!fact.keep_out_of_prompts}
          onPressedChange={(v) => patch({ keep_out_of_prompts: v })}
          title="Never sent to an AI provider"
        >
          Keep out of AI
        </PillToggle>
        <span className="ml-auto flex flex-wrap items-center gap-1">
          {fact.review_state === "needs_review" && (
            <ReviewActions
              entity="fact"
              id={fact.id}
              label={fact.code}
              onEdit={() => onEdit(fact)}
            />
          )}
          {fact.status === "draft" && (
            <Button
              size="xs"
              variant="outline"
              onClick={() => act.mutate({ id: fact.id, action: "approve" })}
              aria-label={`Approve ${fact.code}`}
            >
              Approve
            </Button>
          )}
          {fact.status === "approved" && (
            <Button
              size="xs"
              variant="ghost"
              onClick={() => act.mutate({ id: fact.id, action: "retire" })}
              aria-label={`Retire ${fact.code}`}
            >
              Retire
            </Button>
          )}
          <Button
            size="icon-xs"
            variant="ghost"
            onClick={() => onEdit(fact)}
            aria-label={`Open all details of ${fact.code}`}
          >
            <Pencil aria-hidden="true" />
          </Button>
          <ConfirmButton
            onConfirm={() =>
              remove.mutate(fact.id, {
                onSuccess: () => toast.success("Fact deleted."),
              })
            }
          />
        </span>
      </div>
    </li>
  )
}

/** Create or edit a fact with every field. `fact` null means new; `experienceId` preselects the role. */
export function FactDialog({
  open,
  onOpenChange,
  fact,
  experienceId,
  experiences,
  kind,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  fact: FactOut | null
  experienceId?: string | null
  experiences: ExperienceOut[]
  kind?: FactOut["kind"]
}) {
  const save = useSave<FactOut, FactIn>("facts")
  const [f, setF] = useState<FactIn>((): FactIn =>
    fact
      ? toIn(fact)
      : {
          kind: kind ?? "bullet",
          text: "",
          experience_id: experienceId ?? null,
          tags: [],
          tracks: [],
          canonical_wording: false,
          keep_out_of_prompts: false,
        }
  )
  const [tags, setTags] = useState(csv(f.tags))
  const [tracks, setTracks] = useState(csv(f.tracks))
  const set = <K extends keyof FactIn>(k: K, v: FactIn[K]) =>
    setF((p) => ({ ...p, [k]: v }))

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={fact ? `Edit ${fact.code}` : "Add a fact"}
      description="A fact is one thing that is true. A CV is built from approved facts."
      saving={save.isPending}
      error={save.error}
      onSubmit={() => {
        if (!f.text.trim()) return
        save.mutate(
          {
            id: fact?.id,
            body: {
              ...f,
              code: f.code || undefined,
              text: f.text.trim(),
              tags: parseCsv(tags),
              tracks: parseCsv(tracks),
            },
          },
          {
            onSuccess: () => {
              toast.success(fact ? "Fact saved." : "Fact added as a draft.")
              onOpenChange(false)
            },
          }
        )
      }}
    >
      <Field label="Text">
        {(id) => (
          <Textarea
            id={id}
            autoFocus
            rows={3}
            value={f.text}
            onChange={(e) => set("text", e.target.value)}
            required
          />
        )}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Kind">
          {(id) => (
            <NativeSelect
              id={id}
              value={f.kind}
              onChange={(e) => set("kind", e.target.value as FactIn["kind"])}
            >
              {Object.entries(FACT_KINDS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field label="Role">
          {(id) => (
            <NativeSelect
              id={id}
              value={f.experience_id ?? ""}
              onChange={(e) => set("experience_id", e.target.value || null)}
            >
              <option value="">Not tied to a role</option>
              {experiences.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.org}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field label="Tags" hint="Separate with commas.">
          {(id) => (
            <Input
              id={id}
              value={tags}
              onChange={(e) => setTags(e.target.value)}
            />
          )}
        </Field>
        <Field label="Tracks" hint="Track keys, separated with commas.">
          {(id) => (
            <Input
              id={id}
              value={tracks}
              onChange={(e) => setTracks(e.target.value)}
            />
          )}
        </Field>
      </div>
      <Field
        label="Note to self"
        hint="Why you are sure this is true. Optional."
      >
        {(id) => (
          <Input
            id={id}
            value={f.confidence_note ?? ""}
            onChange={(e) => set("confidence_note", e.target.value || null)}
          />
        )}
      </Field>
      <div className="flex flex-wrap gap-2">
        <PillToggle
          pressed={!!f.canonical_wording}
          onPressedChange={(v) => set("canonical_wording", v)}
        >
          Exact wording
        </PillToggle>
        <PillToggle
          pressed={!!f.keep_out_of_prompts}
          onPressedChange={(v) => set("keep_out_of_prompts", v)}
        >
          Keep out of AI
        </PillToggle>
      </div>
    </FormDialog>
  )
}
