import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  appKeys,
  attachFiles,
  markSubmitted,
  patchApplication,
  type ApplicationSummary,
  type Channel,
} from "./api"
import { CHANNEL_META } from "./application-card"
import { todayIn } from "./format"

/**
 * "I applied myself" (DESIGN 18.2, 18.4). This is the only way a drag reaches Submitted:
 * it records what the owner did, with their date, channel and reference. It never creates
 * submission evidence the system did not witness.
 */
export function AppliedMyselfDialog({
  app,
  timeZone,
  onClose,
}: {
  app: ApplicationSummary | null
  timeZone?: string
  onClose: () => void
}) {
  return (
    <Dialog open={app !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        {app && (
          <AppliedForm
            key={app.id}
            app={app}
            timeZone={timeZone}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function AppliedForm({
  app,
  timeZone,
  onClose,
}: {
  app: ApplicationSummary
  timeZone?: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [date, setDate] = useState(todayIn(timeZone))
  const [channel, setChannel] = useState<Channel>(app.channel ?? "manual")
  const [reference, setReference] = useState("")
  const [files, setFiles] = useState<File[]>([])

  const save = useMutation({
    mutationFn: async () => {
      if (channel !== app.channel) await patchApplication(app.id, { channel })
      const parts = [
        `Applied myself on ${date} via ${CHANNEL_META[channel].label.toLowerCase()}.`,
      ]
      const saved = await markSubmitted(app.id, {
        reference: reference.trim() || null,
        note: parts.join(" "),
      })
      if (files.length) await attachFiles(app.id, files)
      return saved
    },
    onSuccess: () => {
      toast.success(`Recorded: you applied to ${app.employer}.`)
      void qc.invalidateQueries({ queryKey: appKeys.list })
      void qc.invalidateQueries({ queryKey: appKeys.today })
      onClose()
    },
    onError: (e) => toast.error(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>I applied myself</DialogTitle>
        <DialogDescription>
          Record that you sent {app.title} at {app.employer} outside Nchito. It
          counts at once for duplicate checks, employer limits and follow-ups.
          Nothing is marked as sent until you save this.
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-1.5">
        <Label htmlFor="am-date">Date applied</Label>
        <Input
          id="am-date"
          type="date"
          required
          max={todayIn(timeZone)}
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="am-channel">Channel</Label>
        <Select value={channel} onValueChange={(v) => setChannel(v as Channel)}>
          <SelectTrigger id="am-channel" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(CHANNEL_META) as Channel[]).map((c) => (
              <SelectItem key={c} value={c}>
                {CHANNEL_META[c].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="am-ref">Reference (optional)</Label>
        <Input
          id="am-ref"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          placeholder="Confirmation number or email subject"
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="am-files">Files you sent (optional)</Label>
        <Input
          id="am-files"
          type="file"
          multiple
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <p className="text-xs text-faint">
          Kept with the application and shown on its timeline. You can save
          without any.
        </p>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          Record that I applied
        </Button>
      </DialogFooter>
    </form>
  )
}
