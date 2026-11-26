import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  employerKeys,
  employersQuery,
  endCooldown,
  mergeEmployer,
  splitEmployer,
} from "./api"

const fail = (e: unknown) =>
  toast.error(e instanceof Error ? e.message : "That did not work.")

function useRefresh() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: employerKeys.all })
    void qc.invalidateQueries({ queryKey: ["matches"] })
    void qc.invalidateQueries({ queryKey: ["applications"] })
  }
}

/** End a cooldown early. The reason is required and kept, with who and when, in the audit log. */
export function EndCooldownDialog({
  open,
  employerKey,
  name,
  endsOn,
  onOpenChange,
}: {
  open: boolean
  employerKey: string
  name: string
  endsOn: string | null
  onOpenChange: (open: boolean) => void
}) {
  const [reason, setReason] = useState("")
  const refresh = useRefresh()
  const m = useMutation({
    mutationFn: () => endCooldown(employerKey, reason.trim()),
    onSuccess: () => {
      toast.success("Cooldown ended. Your reason is in the audit log.")
      refresh()
      onOpenChange(false)
    },
    onError: fail,
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">
            End the cooldown early
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {name} is cooling down{endsOn ? ` until ${endsOn}` : ""}. Ending it
            lets the next role here go ahead now. Applications that ended or
            went out before today stop counting.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (reason.trim()) m.mutate()
          }}
        >
          <label className="grid gap-1.5 text-sm">
            <span className="eyebrow">Reason (required)</span>
            <Textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!reason.trim() || m.isPending}>
              End cooldown
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Merge this employer into another (the same company under two names). */
export function MergeEmployerDialog({
  open,
  employerKey,
  name,
  onOpenChange,
  onMerged,
}: {
  open: boolean
  employerKey: string
  name: string
  onOpenChange: (open: boolean) => void
  onMerged: (into: string) => void
}) {
  const [into, setInto] = useState("")
  const [remember, setRemember] = useState(true)
  const peers = useQuery({ ...employersQuery("", into), enabled: open })
  const refresh = useRefresh()
  const known = (peers.data ?? []).filter((e) => e.key !== employerKey)
  const m = useMutation({
    mutationFn: () => mergeEmployer(employerKey, into.trim(), remember),
    onSuccess: (r) => {
      toast.success(`Merged. ${r.jobs} roles now count under ${into.trim()}.`)
      refresh()
      onMerged(into.trim())
      onOpenChange(false)
    },
    onError: fail,
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">Merge employers</DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            Merge <b>{name}</b> into another employer. Their roles, history and
            cooldown then count together.
          </DialogDescription>
        </DialogHeader>
        <label className="grid gap-1.5 text-sm">
          <span className="eyebrow">Merge into</span>
          <Input
            value={into}
            onChange={(e) => setInto(e.target.value)}
            placeholder="Start typing a name"
          />
        </label>
        {known.length > 0 && (
          <ul
            aria-label="Employers in your list"
            className="flex flex-wrap gap-1.5"
          >
            {known.slice(0, 8).map((e) => (
              <li key={e.key}>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setInto(e.name)}
                >
                  {e.name}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={remember}
            onCheckedChange={(v) => setRemember(v === true)}
          />
          Remember this name for future postings
        </label>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!into.trim() || m.isPending}
            onClick={() => m.mutate()}
          >
            Merge
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Undo a merge for one name: it becomes its own employer again. */
export function SplitAliasButton({ alias }: { alias: string }) {
  const refresh = useRefresh()
  const m = useMutation({
    mutationFn: () => splitEmployer(alias),
    onSuccess: () => {
      toast.success(`${alias} is its own employer again.`)
      refresh()
    },
    onError: fail,
  })
  return (
    <Button
      size="xs"
      variant="outline"
      disabled={m.isPending}
      aria-label={`Split ${alias} out`}
      onClick={() => m.mutate()}
    >
      Split out
    </Button>
  )
}
