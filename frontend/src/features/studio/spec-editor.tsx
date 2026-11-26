import { useState, type FormEvent, type ReactNode } from "react"
import { Plus, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { ExperienceOut } from "./api"
import { ClaimEditor, ClaimList, type ClaimContext } from "./claims"
import { newKey, type Draft, type DraftItem } from "./draft"

type Edit = (update: (d: Draft) => Draft) => void

function Section({
  title,
  aside,
  children,
}: {
  title: string
  aside?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="grid gap-2" aria-label={title}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <h3 className="eyebrow">{title}</h3>
        {aside && <span className="ml-auto text-xs text-faint">{aside}</span>}
      </div>
      {children}
    </section>
  )
}

const blank = (): DraftItem => ({ key: newKey(), text: "", fact_ids: [] })

/** Where an experience happened, from the Kit ("Copperline Mining Services, Kitwe"). */
export function experienceLine(
  id: string,
  experiences: ExperienceOut[]
): string | null {
  const e = experiences.find((x) => x.id === id)
  if (!e) return null
  return [e.org, e.location].filter(Boolean).join(", ")
}

/** The CV, section by section: headline, summary, competencies, experience bullets, skills. */
export function CvEditor({
  draft,
  edit,
  ctx,
  experiences,
}: {
  draft: Draft
  edit: Edit
  ctx: ClaimContext
  experiences: ExperienceOut[]
}) {
  return (
    <div className="grid gap-6">
      <Section title="Headline">
        <ClaimEditor
          short
          item={draft.headline ?? blank()}
          label="Headline"
          ctx={ctx}
          onChange={(next) => edit((d) => ({ ...d, headline: next }))}
        />
      </Section>
      <Section title="Summary">
        <ClaimEditor
          item={draft.summary ?? blank()}
          label="Summary"
          ctx={ctx}
          onChange={(next) => edit((d) => ({ ...d, summary: next }))}
        />
      </Section>
      <Section title="Competencies" aside="Drag, or use the arrows">
        <ClaimList
          items={draft.competencies}
          listLabel="Competencies"
          labelFor={(i) => `Competency ${i + 1}`}
          addLabel="Add a competency"
          ctx={ctx}
          onChange={(next) => edit((d) => ({ ...d, competencies: next }))}
        />
      </Section>
      {draft.experience.map((e) => (
        <Section
          key={e.key}
          title={`Experience · ${e.title ?? "Role"}`}
          aside={experienceLine(e.experience_id, experiences) ?? undefined}
        >
          <ClaimList
            items={e.bullets}
            listLabel={`Bullets for ${e.title ?? "this role"}`}
            labelFor={(i) => `Bullet ${i + 1}, ${e.title ?? "role"}`}
            addLabel="Add a bullet"
            ctx={ctx}
            onChange={(next) =>
              edit((d) => ({
                ...d,
                experience: d.experience.map((x) =>
                  x.key === e.key ? { ...x, bullets: next } : x
                ),
              }))
            }
          />
        </Section>
      ))}
      <Section title="Skills" aside="Listed as written; not fact-tagged">
        <SkillsEditor
          skills={draft.skills}
          onChange={(next) => edit((d) => ({ ...d, skills: next }))}
        />
      </Section>
    </div>
  )
}

function SkillsEditor({
  skills,
  onChange,
}: {
  skills: string[]
  onChange: (next: string[]) => void
}) {
  const [value, setValue] = useState("")
  const add = (e: FormEvent) => {
    e.preventDefault()
    const v = value.trim()
    if (!v || skills.some((s) => s.toLowerCase() === v.toLowerCase())) return
    onChange([...skills, v])
    setValue("")
  }
  return (
    <div className="grid gap-2">
      <ul
        className="m-0 flex list-none flex-wrap gap-1.5 p-0"
        aria-label="Skills"
      >
        {skills.map((s) => (
          <li
            key={s}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-surface py-0.5 pr-1 pl-2.5 text-sm"
          >
            {s}
            <button
              type="button"
              aria-label={`Remove ${s}`}
              onClick={() => onChange(skills.filter((x) => x !== s))}
              className="grid size-5 place-items-center rounded-full text-faint hover:bg-sunken hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary-ink"
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="flex max-w-sm gap-2">
        <Input
          aria-label="Add a skill"
          placeholder="Add a skill"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button
          type="submit"
          size="sm"
          variant="outline"
          disabled={!value.trim()}
        >
          <Plus aria-hidden="true" />
          Add
        </Button>
      </form>
    </div>
  )
}

/** The cover letter, one claim per paragraph. */
export function LetterEditor({
  draft,
  edit,
  ctx,
}: {
  draft: Draft
  edit: Edit
  ctx: ClaimContext
}) {
  return (
    <Section title="Paragraphs" aside="Drag, or use the arrows">
      <ClaimList
        items={draft.letter}
        listLabel="Letter paragraphs"
        labelFor={(i) => `Paragraph ${i + 1}`}
        addLabel="Add a paragraph"
        ctx={ctx}
        onChange={(next) => edit((d) => ({ ...d, letter: next }))}
      />
    </Section>
  )
}
