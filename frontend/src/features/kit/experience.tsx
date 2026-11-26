import { useState } from "react"
import { Pencil, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import {
  useRemove,
  useSave,
  type ExperienceIn,
  type ExperienceOut,
  type FactOut,
} from "./api"
import {
  ConfirmButton,
  Field,
  FormDialog,
  NeedsReviewChip,
  ReviewActions,
} from "./common"
import { FactRow } from "./fact-row"
import { csv, parseCsv } from "./labels"

type Title = { title: string; start?: string | null; end?: string | null }

const span = (t: Title) =>
  [t.start, t.end ?? (t.start ? "now" : null)].filter(Boolean).join(" to ")

/** A role: organisation, titles, allowed variants, titles never to use, and its facts. */
export function ExperienceCard({
  exp,
  facts,
  onEdit,
  onEditFact,
  onAddFact,
  empty,
}: {
  exp: ExperienceOut
  facts: FactOut[]
  onEdit: (e: ExperienceOut) => void
  onEditFact: (f: FactOut) => void
  onAddFact: (experienceId: string) => void
  empty: string
}) {
  const variants = Object.entries(exp.title_variants ?? {}) as [
    string,
    string[],
  ][]
  return (
    <section
      aria-label={exp.org}
      className="overflow-hidden rounded-lg border border-border bg-surface"
    >
      <header className="grid gap-2 border-b border-border bg-surface-2 px-3.5 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 className="text-base font-semibold">{exp.org}</h3>
          {exp.location && (
            <span className="text-sm text-muted-foreground">
              {exp.location}
            </span>
          )}
          {exp.review_state === "needs_review" && <NeedsReviewChip />}
          <span className="ml-auto flex flex-wrap items-center gap-1">
            {exp.review_state === "needs_review" && (
              <ReviewActions
                entity="experience"
                id={exp.id}
                label={exp.org}
                onEdit={() => onEdit(exp)}
              />
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onEdit(exp)}
              aria-label={`Edit ${exp.org}`}
            >
              <Pencil aria-hidden="true" />
              Edit
            </Button>
          </span>
        </div>
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0 text-sm">
          {(exp.titles ?? []).map((t) => (
            <li key={`${t.title}-${t.start}`} className="flex gap-2">
              <span className="font-medium">{t.title}</span>
              <span className="num text-muted-foreground">{span(t)}</span>
            </li>
          ))}
        </ul>
        {(variants.length > 0 || (exp.forbidden_titles ?? []).length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 text-sm">
            {variants.map(([track, titles]) => (
              <span
                key={track}
                className="inline-flex flex-wrap items-center gap-1"
              >
                <Chip tone="primary">{track}</Chip>
                <span className="text-muted-foreground">
                  {titles.join(", ")}
                </span>
              </span>
            ))}
            {(exp.forbidden_titles ?? []).map((t) => (
              <Chip key={t} tone="danger" title="Never use this title">
                Never: {t}
              </Chip>
            ))}
          </div>
        )}
      </header>
      {facts.length > 0 ? (
        <ul className="m-0 list-none p-0">
          {facts.map((f) => (
            <FactRow key={f.id} fact={f} onEdit={onEditFact} />
          ))}
        </ul>
      ) : (
        <p className="px-3.5 py-3 text-sm text-muted-foreground">{empty}</p>
      )}
      <div className="border-t border-border px-2 py-1.5">
        <Button size="sm" variant="ghost" onClick={() => onAddFact(exp.id)}>
          <Plus aria-hidden="true" />
          Add a fact to {exp.org}
        </Button>
      </div>
    </section>
  )
}

type VariantRow = { track: string; titles: string }

export function ExperienceDialog({
  open,
  onOpenChange,
  exp,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  exp: ExperienceOut | null
}) {
  const save = useSave<ExperienceOut, ExperienceIn>("experiences")
  const remove = useRemove("experiences")
  const [org, setOrg] = useState(exp?.org ?? "")
  const [location, setLocation] = useState(exp?.location ?? "")
  const [titles, setTitles] = useState<Title[]>(
    exp?.titles?.length ? exp.titles : [{ title: "", start: "", end: "" }]
  )
  const [variants, setVariants] = useState<VariantRow[]>(
    Object.entries((exp?.title_variants ?? {}) as Record<string, string[]>).map(
      ([track, t]) => ({ track, titles: csv(t) })
    )
  )
  const [forbidden, setForbidden] = useState(csv(exp?.forbidden_titles))

  const setTitle = (i: number, p: Partial<Title>) =>
    setTitles((ts) => ts.map((t, j) => (j === i ? { ...t, ...p } : t)))

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title={exp ? `Edit ${exp.org}` : "Add an experience"}
      description="An employer or organisation, the titles you held, and the title variants allowed for each track."
      saving={save.isPending}
      error={save.error}
      onSubmit={() => {
        if (!org.trim()) return
        const cleanTitles = titles
          .filter((t) => t.title.trim())
          .map((t) => ({
            title: t.title.trim(),
            start: t.start || null,
            end: t.end || null,
          }))
        save.mutate(
          {
            id: exp?.id,
            body: {
              org: org.trim(),
              location: location.trim() || null,
              titles: cleanTitles,
              start_date: exp?.start_date ?? null,
              end_date: exp?.end_date ?? null,
              title_variants: Object.fromEntries(
                variants
                  .filter((v) => v.track.trim())
                  .map((v) => [v.track.trim(), parseCsv(v.titles)])
              ),
              forbidden_titles: parseCsv(forbidden),
              sort_order: exp?.sort_order ?? 0,
            },
          },
          {
            onSuccess: () => {
              toast.success("Experience saved.")
              onOpenChange(false)
            },
          }
        )
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Organisation">
          {(id) => (
            <Input
              id={id}
              autoFocus
              required
              value={org}
              onChange={(e) => setOrg(e.target.value)}
            />
          )}
        </Field>
        <Field label="Location">
          {(id) => (
            <Input
              id={id}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          )}
        </Field>
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">Titles you held</legend>
        {titles.map((t, i) => (
          <div
            key={i}
            className="grid grid-cols-[1fr_6.5rem_6.5rem_auto] gap-2"
          >
            <Input
              aria-label={`Title ${i + 1}`}
              placeholder="Title"
              value={t.title}
              onChange={(e) => setTitle(i, { title: e.target.value })}
            />
            <Input
              aria-label={`Title ${i + 1} start`}
              placeholder="From"
              value={t.start ?? ""}
              onChange={(e) => setTitle(i, { start: e.target.value })}
            />
            <Input
              aria-label={`Title ${i + 1} end`}
              placeholder="To (blank: now)"
              value={t.end ?? ""}
              onChange={(e) => setTitle(i, { end: e.target.value })}
            />
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label={`Remove title ${i + 1}`}
              onClick={() => setTitles((ts) => ts.filter((_, j) => j !== i))}
            >
              <X aria-hidden="true" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="w-fit"
          onClick={() =>
            setTitles((ts) => [...ts, { title: "", start: "", end: "" }])
          }
        >
          <Plus aria-hidden="true" />
          Add a title
        </Button>
      </fieldset>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">
          Allowed title variants per track
        </legend>
        {variants.map((v, i) => (
          <div key={i} className="grid grid-cols-[8rem_1fr_auto] gap-2">
            <Input
              aria-label={`Variant ${i + 1} track`}
              placeholder="Track key"
              value={v.track}
              onChange={(e) =>
                setVariants((vs) =>
                  vs.map((x, j) =>
                    j === i ? { ...x, track: e.target.value } : x
                  )
                )
              }
            />
            <Input
              aria-label={`Variant ${i + 1} titles`}
              placeholder="Titles, separated with commas"
              value={v.titles}
              onChange={(e) =>
                setVariants((vs) =>
                  vs.map((x, j) =>
                    j === i ? { ...x, titles: e.target.value } : x
                  )
                )
              }
            />
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label={`Remove variant ${i + 1}`}
              onClick={() => setVariants((vs) => vs.filter((_, j) => j !== i))}
            >
              <X aria-hidden="true" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="w-fit"
          onClick={() =>
            setVariants((vs) => [...vs, { track: "", titles: "" }])
          }
        >
          <Plus aria-hidden="true" />
          Add a variant
        </Button>
      </fieldset>
      <Field label="Titles never to use" hint="Separate with commas.">
        {(id) => (
          <Input
            id={id}
            value={forbidden}
            onChange={(e) => setForbidden(e.target.value)}
          />
        )}
      </Field>
      {exp && (
        <div>
          <ConfirmButton
            label="Delete this experience"
            onConfirm={() =>
              remove.mutate(exp.id, {
                onSuccess: () => {
                  toast.success("Experience deleted.")
                  onOpenChange(false)
                },
              })
            }
          />
        </div>
      )}
    </FormDialog>
  )
}
