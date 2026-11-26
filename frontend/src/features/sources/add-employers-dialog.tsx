import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Plus } from "lucide-react"
import { Chip } from "@/components/chip"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { createEmployer, detectBoard, sourceKeys, type Detected } from "./api"
import { boardLabel } from "./board"

type Row = { url: string; detected: Detected; name: string }

const urlsFrom = (text: string) => [
  ...new Set(
    text
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean)
  ),
]

/**
 * Add one employer, or several at once, by pasting careers URLs. The board type is
 * detected and shown before anything is saved.
 */
export function AddEmployersDialog() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")
  const [rows, setRows] = useState<Row[] | null>(null)

  const reset = () => {
    setText("")
    setRows(null)
  }

  const check = useMutation({
    mutationFn: async () => {
      const urls = urlsFrom(text)
      return Promise.all(
        urls.map(async (url): Promise<Row> => {
          const detected = await detectBoard(url)
          return { url, detected, name: detected.employer_name ?? "" }
        })
      )
    },
    onSuccess: setRows,
    onError: (e) => toast.error(e.message),
  })

  const ok = (rows ?? []).filter((r) => r.detected.connector && r.name.trim())
  const save = useMutation({
    mutationFn: async () => {
      for (const r of ok)
        await createEmployer({
          name: r.name.trim(),
          board_type: r.detected.connector!,
          board_slug: r.detected.board_slug!,
          priority: 3,
          always_ask_first: false,
        })
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: sourceKeys.employers })
      toast.success(
        ok.length === 1
          ? `Watching ${ok[0].name}`
          : `Watching ${ok.length} employers`
      )
      setOpen(false)
      reset()
    },
    onError: (e) => toast.error(e.message),
  })

  const count = urlsFrom(text).length

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden="true" />
          Add employer
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add employers</DialogTitle>
          <DialogDescription>
            Paste a careers page link, or several (one per line). We detect the
            board type and show it before anything is saved.
          </DialogDescription>
        </DialogHeader>

        {rows === null ? (
          <div className="grid gap-1.5">
            <Label htmlFor="emp-urls">Careers links</Label>
            <Textarea
              id="emp-urls"
              rows={5}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={
                "https://boards.greenhouse.io/example\nhttps://jobs.lever.co/example"
              }
            />
          </div>
        ) : (
          <ul className="grid gap-2" aria-label="Detected boards">
            {rows.map((r, i) => (
              <li
                key={r.url}
                className="grid gap-1.5 rounded-md border border-border p-2.5"
              >
                <span className="truncate text-xs text-muted-foreground">
                  {r.url}
                </span>
                {r.detected.connector ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip tone="good">
                      {boardLabel(r.detected.connector)} detected
                    </Chip>
                    <Input
                      aria-label={`Employer name for ${r.url}`}
                      className="max-w-60"
                      value={r.name}
                      onChange={(e) =>
                        setRows((cur) =>
                          cur!.map((x, j) =>
                            j === i ? { ...x, name: e.target.value } : x
                          )
                        )
                      }
                    />
                  </div>
                ) : (
                  <Chip tone="warn" className="w-fit">
                    Board type not recognised. This link will be skipped.
                  </Chip>
                )}
              </li>
            ))}
          </ul>
        )}

        <DialogFooter>
          {rows === null ? (
            <Button
              onClick={() => check.mutate()}
              disabled={count === 0 || check.isPending}
            >
              {check.isPending
                ? "Checking..."
                : count > 1
                  ? `Check ${count} links`
                  : "Check link"}
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setRows(null)}>
                Back
              </Button>
              <Button
                onClick={() => save.mutate()}
                disabled={ok.length === 0 || save.isPending}
              >
                {save.isPending
                  ? "Saving..."
                  : ok.length === 1
                    ? "Watch this employer"
                    : `Watch ${ok.length} employers`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
