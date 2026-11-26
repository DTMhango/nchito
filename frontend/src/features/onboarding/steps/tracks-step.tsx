import { useId, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  useKitList,
  useSave,
  type TrackIn,
  type TrackOut,
} from "@/features/kit/api"

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")

/** A track is a kind of role you go for. Add one or more; edit them later under Kit. */
export function TracksStep({ next }: { next: () => void }) {
  const uid = useId()
  const list = useKitList<TrackOut>("tracks")
  const save = useSave<TrackOut, TrackIn>("tracks")
  const [name, setName] = useState("")
  const [titles, setTitles] = useState("")
  const tracks = list.data ?? []
  const key = slug(name)
  const clash = tracks.some((t) => t.key === key)

  const add = () =>
    save.mutate(
      {
        body: {
          key,
          name: name.trim(),
          priority: tracks.length + 1,
          example_titles: titles
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
        },
      },
      {
        onSuccess: () => {
          setName("")
          setTitles("")
        },
      }
    )

  return (
    <div className="grid max-w-[560px] gap-4">
      {tracks.length > 0 && (
        <ul aria-label="Your tracks" className="grid gap-1.5">
          {tracks.map((t) => (
            <li
              key={t.id}
              className="rounded-md border border-border bg-surface px-3 py-2"
            >
              <span className="font-semibold">{t.name}</span>
              {t.example_titles.length > 0 && (
                <span className="text-muted-foreground">
                  {" "}
                  · {t.example_titles.join(", ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <form
        aria-label="Add a track"
        className="grid gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (key && !clash) add()
        }}
      >
        <div className="grid gap-1">
          <label htmlFor={`${uid}-n`} className="font-semibold">
            Kind of role
          </label>
          <Input
            id={`${uid}-n`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
          />
          {clash && (
            <p className="text-sm text-danger">You already have that track.</p>
          )}
        </div>
        <div className="grid gap-1">
          <label htmlFor={`${uid}-t`} className="font-semibold">
            Job titles that fit it (optional, separated by commas)
          </label>
          <Input
            id={`${uid}-t`}
            value={titles}
            onChange={(e) => setTitles(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="flex gap-2">
          <Button type="submit" disabled={!key || clash || save.isPending}>
            Add track
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={tracks.length === 0}
            onClick={next}
          >
            Continue
          </Button>
        </div>
        {save.isError && (
          <p role="alert" className="text-sm text-danger">
            {save.error.message}
          </p>
        )}
      </form>
    </div>
  )
}
