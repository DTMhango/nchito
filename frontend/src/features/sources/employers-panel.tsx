import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Building2, Pencil, ShieldQuestion, Trash2 } from "lucide-react"
import { Chip } from "@/components/chip"
import { DataTable, type Column } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
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
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  deleteEmployer,
  employersQuery,
  sourceKeys,
  toEmployerInput,
  updateEmployer,
  type Employer,
} from "./api"
import { AddEmployersDialog } from "./add-employers-dialog"
import { boardLabel } from "./board"

export function EmployersPanel() {
  const qc = useQueryClient()
  const q = useQuery(employersQuery())
  const [editing, setEditing] = useState<Employer | null>(null)

  const remove = useMutation({
    mutationFn: (e: Employer) => deleteEmployer(e.id),
    onSuccess: (_d, e) => {
      qc.invalidateQueries({ queryKey: sourceKeys.employers })
      toast.success(`Stopped watching ${e.name}`)
    },
    onError: (e) => toast.error(e.message),
  })

  if (q.isPending) return <Skeleton className="h-40 w-full" />
  if (q.isError)
    return (
      <EmptyState
        icon={Building2}
        title="Could not load employers"
        description={q.error.message}
      />
    )

  const columns: Column<Employer>[] = [
    {
      id: "name",
      header: "Employer",
      sortValue: (e) => e.name,
      cell: (e) => (
        <div className="grid gap-0.5">
          <span className="font-medium">{e.name}</span>
          <span className="text-xs text-muted-foreground">{e.board_slug}</span>
        </div>
      ),
    },
    {
      id: "board",
      header: "Board",
      sortValue: (e) => e.board_type,
      cell: (e) => <Chip tone="line">{boardLabel(e.board_type)}</Chip>,
    },
    {
      id: "priority",
      header: "Priority",
      sortValue: (e) => e.priority ?? 3,
      cell: (e) => <span className="num">{e.priority ?? 3}</span>,
    },
    {
      id: "cooldown",
      header: "Cooldown",
      hideBelow: "md",
      cell: (e) =>
        e.cooldown_days === null || e.cooldown_days === undefined ? (
          <span className="text-faint">Default</span>
        ) : (
          <span>{e.cooldown_days} days</span>
        ),
    },
    {
      id: "ask",
      header: "Ask first",
      hideBelow: "sm",
      cell: (e) =>
        e.always_ask_first ? (
          <Chip tone="primary" icon={ShieldQuestion}>
            Always ask me first
          </Chip>
        ) : (
          <span className="text-faint">No</span>
        ),
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (e) => (
        <span className="inline-flex gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Edit ${e.name}`}
            onClick={() => setEditing(e)}
          >
            <Pencil aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Stop watching ${e.name}`}
            onClick={() => remove.mutate(e)}
          >
            <Trash2 aria-hidden="true" />
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          Employers whose boards are checked directly on every sweep.
        </p>
        <AddEmployersDialog />
      </div>
      <DataTable
        columns={columns}
        rows={q.data}
        getRowId={(e) => e.id}
        caption="Watched employers"
        initialSort={{ id: "priority", dir: "asc" }}
        empty={
          <EmptyState
            icon={Building2}
            title="No watched employers yet"
            description="Paste a careers page link and we will detect the board type."
            actions={<AddEmployersDialog />}
          />
        }
      />
      <EditEmployer employer={editing} onClose={() => setEditing(null)} />
    </div>
  )
}

function EditEmployer({
  employer,
  onClose,
}: {
  employer: Employer | null
  onClose: () => void
}) {
  return (
    <Dialog open={employer !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        {employer && (
          <EditBody key={employer.id} employer={employer} onClose={onClose} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function EditBody({
  employer,
  onClose,
}: {
  employer: Employer
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [priority, setPriority] = useState(String(employer.priority ?? 3))
  const [cooldown, setCooldown] = useState(
    employer.cooldown_days == null ? "" : String(employer.cooldown_days)
  )
  const [ask, setAsk] = useState(employer.always_ask_first ?? false)

  const p = Number(priority)
  const c = cooldown.trim() === "" ? null : Number(cooldown)
  const invalid =
    !Number.isInteger(p) ||
    p < 1 ||
    p > 5 ||
    (c !== null && (!Number.isInteger(c) || c < 0))

  const save = useMutation({
    mutationFn: () =>
      updateEmployer(employer.id, {
        ...toEmployerInput(employer),
        priority: p,
        cooldown_days: c,
        always_ask_first: ask,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: sourceKeys.employers })
      toast.success(`Saved ${employer.name}`)
      onClose()
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <>
      <DialogHeader>
        <DialogTitle>{employer.name}</DialogTitle>
        <DialogDescription>
          {boardLabel(employer.board_type)} board, {employer.board_slug}
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-4">
        <div className="grid gap-1.5">
          <Label htmlFor="emp-priority">
            Priority (1 is highest, 5 lowest)
          </Label>
          <Input
            id="emp-priority"
            inputMode="numeric"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            aria-invalid={!(p >= 1 && p <= 5)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="emp-cooldown">
            Cooldown between applications (days)
          </Label>
          <Input
            id="emp-cooldown"
            inputMode="numeric"
            value={cooldown}
            placeholder="Use the default"
            onChange={(e) => setCooldown(e.target.value)}
          />
        </div>
        <div className="flex items-start justify-between gap-3">
          <Label htmlFor="emp-ask" className="grid gap-0.5 font-normal">
            <span className="font-medium">Always ask me first</span>
            <span className="text-xs text-muted-foreground">
              Nothing is sent to this employer without your approval, whatever
              the autopilot mode.
            </span>
          </Label>
          <Switch id="emp-ask" checked={ask} onCheckedChange={setAsk} />
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          onClick={() => save.mutate()}
          disabled={invalid || save.isPending}
        >
          {save.isPending ? "Saving..." : "Save"}
        </Button>
      </DialogFooter>
    </>
  )
}
