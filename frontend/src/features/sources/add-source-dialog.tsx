import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Plus } from "lucide-react"
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
import { createSource, sourceKeys } from "./api"
import {
  ConnectorFields,
  JobSpyNotInstalled,
  useSearchConnections,
  useSourceSettings,
} from "./connector-form"
import {
  buildConfig,
  CONNECTOR_ACCESS,
  CONNECTOR_INFO,
  emptyDraft,
  isNotInstalled,
  NEW_CONNECTORS,
  type Draft,
  type NewConnector,
} from "./connectors"

/** Add a JobSpy, careers page or web search source. Board sources are added from Watched employers. */
export function AddSourceDialog() {
  const qc = useQueryClient()
  const nameId = useId()
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<NewConnector>("careers_page")
  const [name, setName] = useState("")
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [problem, setProblem] = useState<string | null>(null)
  const settings = useSourceSettings()
  const connections = useSearchConnections()

  const reset = () => {
    setKind("careers_page")
    setName("")
    setDraft(emptyDraft())
    setProblem(null)
    create.reset()
  }

  const create = useMutation({
    mutationFn: (config: Record<string, unknown>) =>
      createSource({
        connector: kind,
        name: name.trim() || CONNECTOR_INFO[kind].label,
        access: CONNECTOR_ACCESS[kind],
        config,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: sourceKeys.sources })
      toast.success(`Added ${name.trim() || CONNECTOR_INFO[kind].label}`)
      setOpen(false)
      reset()
    },
  })

  const submit = () => {
    const built = buildConfig(kind, draft, settings, connections)
    if (!built.ok) return setProblem(built.error)
    setProblem(null)
    create.mutate(built.config)
  }

  const error = create.error?.message ?? null
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">
          <Plus aria-hidden="true" /> Add source
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <form
          aria-label="Add a source"
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <DialogHeader>
            <DialogTitle>Add a source</DialogTitle>
            <DialogDescription>
              Job boards with an API are added from Watched employers. These
              read the wider web.
            </DialogDescription>
          </DialogHeader>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">Kind</legend>
            {NEW_CONNECTORS.map((k) => (
              <label
                key={k}
                className="flex items-start gap-2 rounded-md border border-border p-2.5 text-sm"
              >
                <input
                  type="radio"
                  name="source-kind"
                  className="mt-1"
                  checked={kind === k}
                  onChange={() => {
                    setKind(k)
                    setDraft(emptyDraft())
                    setProblem(null)
                    create.reset()
                  }}
                />
                <span className="grid gap-0.5">
                  <span className="font-medium">{CONNECTOR_INFO[k].label}</span>
                  <span className="text-muted-foreground">
                    {CONNECTOR_INFO[k].blurb}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="grid gap-1.5">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={name}
              placeholder={CONNECTOR_INFO[kind].label}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <ConnectorFields kind={kind} draft={draft} onChange={setDraft} />
          {problem && (
            <p role="alert" className="text-sm text-danger">
              {problem}
            </p>
          )}
          {error &&
            (isNotInstalled(error) ? (
              <JobSpyNotInstalled />
            ) : (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            ))}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setOpen(false)
                reset()
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Adding..." : "Add source"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
