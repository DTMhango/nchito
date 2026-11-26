import { useId, useState } from "react"
import { CircleHelp, Printer, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import type { FactIndex } from "@/features/studio/draft"
import type { PackItem, PackSection } from "../w3-pending-types"
import { ClaimView, FactChips } from "./claim-view"

export const UNKNOWN_WORDS = "Decide before the interview"

export type SectionActions = {
  saveItem: (itemId: string, text: string) => void
  saveNotes: (notes: string) => void
  regenerate: () => void
  restore: (version: number) => void
  favourite: (itemId: string, on: boolean) => void
  busy: boolean
}

const QUESTION_ORDER = ["technical", "leadership", "behavioural", "motivation"]

function Logistics({ item, index }: { item: PackItem; index: FactIndex }) {
  const unknown = item.value == null || item.value.trim() === ""
  return (
    <li
      data-pack-item={item.id}
      data-state={unknown ? "unknown" : "known"}
      className="grid gap-1 rounded-md border border-border bg-surface p-3 sm:grid-cols-[14rem_1fr] sm:items-center"
    >
      <span className="font-semibold">{item.label}</span>
      <span className="flex flex-wrap items-center gap-1.5">
        {unknown ? (
          <Chip tone="warn" icon={CircleHelp}>
            {UNKNOWN_WORDS}
          </Chip>
        ) : (
          <>
            <span>{item.value}</span>
            <FactChips item={item} index={index} />
          </>
        )}
      </span>
    </li>
  )
}

function Body({
  section,
  index,
  actions,
}: {
  section: PackSection
  index: FactIndex
  actions: SectionActions
}) {
  const claim = (
    it: PackItem,
    extra?: { lead?: string | null; fav?: boolean }
  ) => (
    <ClaimView
      key={it.id}
      item={it}
      index={index}
      lead={extra?.lead}
      saving={actions.busy}
      onSave={(text) => actions.saveItem(it.id, text)}
      onFavourite={
        extra?.fav ? (on) => actions.favourite(it.id, on) : undefined
      }
    />
  )
  if (section.key === "logistics")
    return (
      <ul className="m-0 grid list-none gap-2 p-0">
        {section.items.map((it) => (
          <Logistics key={it.id} item={it} index={index} />
        ))}
      </ul>
    )
  if (section.key === "questions") {
    const cats = [
      ...QUESTION_ORDER,
      ...section.items.map((i) => i.category ?? "other"),
    ].filter((c, i, a) => a.indexOf(c) === i)
    return (
      <div className="grid gap-4">
        {cats.map((c) => {
          const items = section.items.filter(
            (i) => (i.category ?? "other") === c
          )
          if (!items.length) return null
          return (
            <div key={c} className="grid gap-2">
              <h4 className="eyebrow capitalize">{c}</h4>
              <ul className="m-0 grid list-none gap-2 p-0">
                {items.map((it) => claim(it, { lead: it.question }))}
              </ul>
            </div>
          )
        })}
      </div>
    )
  }
  if (section.key === "stories") {
    const sorted = [...section.items].sort(
      (a, b) => Number(!!b.favourite) - Number(!!a.favourite)
    )
    return (
      <ul className="m-0 grid list-none gap-2 p-0">
        {sorted.map((it) =>
          claim(it, {
            lead: it.requirement ? `For: ${it.requirement}` : null,
            fav: true,
          })
        )}
      </ul>
    )
  }
  return (
    <ul className="m-0 grid list-none gap-2 p-0">
      {section.items.map((it) => claim(it))}
    </ul>
  )
}

/** One section of the pack: its lines, version switch, regenerate, and the owner's notes. */
export function PackSectionView({
  section,
  index,
  actions,
}: {
  section: PackSection
  index: FactIndex
  actions: SectionActions
}) {
  const notesId = useId()
  const [notes, setNotes] = useState(section.notes)
  const dirty = notes !== section.notes
  return (
    <section
      aria-label={section.title}
      id={`pack-${section.key}`}
      className="grid gap-2.5"
    >
      <SectionHeader
        title={section.title}
        aside={
          section.versions.length > 1
            ? `Version ${section.version} of ${section.versions.length}`
            : undefined
        }
        action={
          <span className="inline-flex items-center gap-1.5">
            {section.versions.length > 1 && (
              <select
                aria-label={`Version of ${section.title}`}
                value={section.version}
                disabled={actions.busy}
                onChange={(e) => actions.restore(Number(e.target.value))}
                className="h-7 rounded-md border border-border bg-transparent px-1.5 text-xs"
              >
                {section.versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    Version {v.version}: {v.note}
                  </option>
                ))}
              </select>
            )}
            {section.key === "crib" && (
              <Button
                size="xs"
                variant="outline"
                onClick={() => window.print()}
              >
                <Printer aria-hidden="true" />
                Print
              </Button>
            )}
            <Button
              size="xs"
              variant="ghost"
              disabled={actions.busy}
              onClick={actions.regenerate}
              aria-label={`Regenerate ${section.title}`}
            >
              <RefreshCw aria-hidden="true" />
              Regenerate
            </Button>
          </span>
        }
      />
      {section.key === "crib" ? (
        <div id="crib-print" className="grid gap-2">
          <Body section={section} index={index} actions={actions} />
        </div>
      ) : (
        <Body section={section} index={index} actions={actions} />
      )}
      <div className="grid gap-1.5">
        <label htmlFor={notesId} className="text-sm font-semibold">
          Your notes on {section.title.toLowerCase()}
        </label>
        <Textarea
          id={notesId}
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Anything you want to remember. Notes stay when you regenerate."
        />
        {dirty && (
          <Button
            size="xs"
            className="justify-self-start"
            disabled={actions.busy}
            onClick={() => actions.saveNotes(notes)}
          >
            Save notes
          </Button>
        )}
      </div>
    </section>
  )
}
