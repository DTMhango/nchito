import { useState } from "react"
import { FileArchive, FolderOpen, LayoutTemplate, Sparkles } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  ImportFlow,
  IMPORT_SOURCES,
} from "@/features/settings/data/import-flow"
import { ReviewGroups } from "../review-groups"
import type { Local, StartKind } from "../state"

const OPTIONS: {
  kind: StartKind
  icon: LucideIcon
  title: string
  body: string
}[] = [
  {
    kind: "empty",
    icon: Sparkles,
    title: "Start empty",
    body: "Enter who you are yourself. Nothing is assumed.",
  },
  {
    kind: "kit_file",
    icon: FileArchive,
    title: "From a kit file",
    body: "A .kit.zip you exported earlier, from this app or another copy.",
  },
  {
    kind: "template",
    icon: LayoutTemplate,
    title: "From a shareable template",
    body: "Someone's rubrics, templates and sources, without any of their personal details.",
  },
  {
    kind: "old_kit",
    icon: FolderOpen,
    title: "From my old job-hunting folder",
    body: "Zip the folder and bring it in. Everything arrives unconfirmed so you can check it.",
  },
]

const SOURCE_FOR: Record<Exclude<StartKind, "empty">, number> = {
  kit_file: 0,
  template: 0,
  old_kit: 1,
}

export function StartStep({
  local,
  update,
  next,
}: {
  local: Local
  update: (p: Partial<Local>) => void
  next: () => void
}) {
  const kind = local.start
  const [imported, setImported] = useState(false)
  return (
    <div className="grid gap-5">
      <div
        role="radiogroup"
        aria-label="How do you want to start?"
        className="grid gap-2 sm:grid-cols-2"
      >
        {OPTIONS.map((o) => (
          <button
            key={o.kind}
            type="button"
            role="radio"
            aria-checked={kind === o.kind}
            onClick={() => update({ start: o.kind })}
            className={cn(
              "grid gap-1 rounded-md border border-border bg-surface p-3 text-left hover:bg-sunken",
              kind === o.kind &&
                "border-primary shadow-[0_0_0_2px_var(--t-ring)]"
            )}
          >
            <span className="flex items-center gap-2 font-semibold">
              <o.icon className="size-4 text-primary-ink" aria-hidden="true" />
              {o.title}
            </span>
            <span className="text-sm text-muted-foreground">{o.body}</span>
          </button>
        ))}
      </div>

      {kind === "empty" && (
        <div className="flex items-center gap-3">
          <p className="text-muted-foreground">
            Good. The next steps ask for everything in turn.
          </p>
          <Button onClick={next}>Continue</Button>
        </div>
      )}

      {kind && kind !== "empty" && (
        <div className="grid gap-4">
          {(kind === "kit_file" || kind === "template") && (
            <p className="max-w-[60ch] text-muted-foreground">
              {kind === "template"
                ? "A template brings in the setup only: rubrics, templates, themes and sources. Your facts and answers you still enter yourself."
                : "A kit file brings in the facts, answers and rules inside it, marked as needing your review."}
            </p>
          )}
          <ImportFlow
            key={kind}
            sources={[IMPORT_SOURCES[SOURCE_FOR[kind]]]}
            onDone={(_, source) => {
              setImported(true)
              if (source === "old_kit_zip") update({ oldKit: true })
            }}
          />
          {imported && (
            <section aria-label="Review what came in" className="grid gap-3">
              <h3 className="text-md">Review what came in</h3>
              <p className="max-w-[60ch] text-muted-foreground">
                Decisive items come first. You can also do this later from the
                Kit.
              </p>
              <ReviewGroups stale={local.oldKit} />
            </section>
          )}
        </div>
      )}
    </div>
  )
}
