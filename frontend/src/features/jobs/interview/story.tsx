import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Pencil, RotateCw, Star } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import type { FactIndex } from "@/features/studio/draft"
import { editStory, packKeys, refusalCode, setFavourite } from "./api"
import { claimFlags, FactChips } from "./claim-view"
import { Chip } from "@/components/chip"
import type { Story } from "./shapes"

const STAR = ["situation", "task", "action", "result"] as const
type Fields = Pick<Story, "title" | "requirement" | (typeof STAR)[number]>

/** One story of the bank: STAR text, its facts, favourite, and an owner edit guarded by version. */
export function StoryCard({
  jobId,
  story,
  index,
  baseVersion,
  locked,
}: {
  jobId: string
  story: Story
  index: FactIndex
  /** The `stories` section version this card was rendered from (`base_version`). */
  baseVersion: number
  /** True while the pack is being generated: edits wait. */
  locked: boolean
}) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Fields | null>(null)
  const [conflict, setConflict] = useState(false)
  const refresh = () => qc.invalidateQueries({ queryKey: packKeys.pack(jobId) })

  const fav = useMutation({
    mutationFn: (on: boolean) => setFavourite(jobId, story.id, on),
    onSuccess: refresh,
  })
  const save = useMutation({
    mutationFn: (f: Fields) =>
      editStory(jobId, story.id, { ...f, base_version: baseVersion }),
    onSuccess: () => {
      setDraft(null)
      return refresh()
    },
    onError: (e) => {
      if (refusalCode(e) === "version_conflict") setConflict(true)
    },
  })

  const text = STAR.map((k) => story[k]).join(" ")
  const flags = claimFlags(story.id, { text, fact_ids: story.fact_ids }, index)
  const label = story.title

  return (
    <li
      data-pack-item={story.id}
      data-trace={flags.length ? "flagged" : "ok"}
      className={cn(
        "grid gap-1.5 rounded-md border border-border bg-surface p-3",
        flags.length > 0 && "border-l-4 border-l-danger"
      )}
    >
      <div className="flex items-start gap-2">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <p className="font-semibold">{story.title}</p>
          {story.requirement && (
            <span className="text-xs text-muted-foreground">
              For: {story.requirement}
            </span>
          )}
        </div>
        <Button
          size="icon-xs"
          variant="ghost"
          aria-pressed={story.favourite}
          disabled={fav.isPending || locked}
          aria-label={
            story.favourite
              ? `Remove from favourites: ${label}`
              : `Favourite: ${label}`
          }
          onClick={() => fav.mutate(!story.favourite)}
        >
          <Star
            aria-hidden="true"
            className={cn(story.favourite && "fill-current text-warn")}
          />
        </Button>
        {!draft && (
          <Button
            size="icon-xs"
            variant="ghost"
            disabled={locked}
            aria-label={`Edit story: ${label}`}
            onClick={() => {
              setConflict(false)
              save.reset()
              setDraft({
                title: story.title,
                requirement: story.requirement,
                situation: story.situation,
                task: story.task,
                action: story.action,
                result: story.result,
              })
            }}
          >
            <Pencil aria-hidden="true" />
          </Button>
        )}
      </div>

      {draft ? (
        <div className="grid gap-2">
          <label className="grid gap-1 text-sm font-semibold">
            Title
            <Input
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              className="font-normal"
            />
          </label>
          {STAR.map((k) => (
            <label
              key={k}
              className="grid gap-1 text-sm font-semibold capitalize"
            >
              {k}
              <Textarea
                rows={2}
                value={draft[k]}
                onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                className="font-normal normal-case"
              />
            </label>
          ))}
          {conflict ? (
            <div
              role="alert"
              data-conflict
              className="grid gap-2 rounded-md border border-warn bg-warn-soft p-2 text-sm"
            >
              <span>
                These stories were changed elsewhere since you opened them.
                Reload to see the latest version, then make your edit again.
              </span>
              <Button
                size="xs"
                className="justify-self-start"
                onClick={() => {
                  setDraft(null)
                  setConflict(false)
                  void refresh()
                }}
              >
                <RotateCw aria-hidden="true" />
                Reload
              </Button>
            </div>
          ) : (
            save.isError && (
              <p role="alert" className="text-sm text-danger">
                {save.error.message}
              </p>
            )
          )}
          <div className="flex gap-1.5">
            <Button
              size="xs"
              disabled={save.isPending || conflict || !draft.title.trim()}
              onClick={() => save.mutate(draft)}
            >
              Save story
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setDraft(null)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <dl className="grid gap-1 text-sm">
          {STAR.map((k) => (
            <div key={k} className="grid grid-cols-[5.5rem_1fr] gap-2">
              <dt className="font-semibold text-muted-foreground capitalize">
                {k}
              </dt>
              <dd>{story[k]}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        <FactChips factIds={story.fact_ids} index={index} />
        {flags.map((f) => (
          <Chip key={f} tone="danger" className="whitespace-normal">
            {f}
          </Chip>
        ))}
      </div>
    </li>
  )
}
