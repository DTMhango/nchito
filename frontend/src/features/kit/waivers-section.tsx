import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SectionHeader } from "@/components/page-header"
import { applicationsQuery } from "@/features/applications/api"
import {
  listWaivers,
  removeWaiver,
  useKitList,
  waiveGuardrail,
  waiversKey,
  type GuardrailOut,
} from "./api"

const SELECT =
  "h-9 w-full rounded-md border border-input bg-surface px-2 text-sm field-focus"

/**
 * Waivers: a "block, waivable once" guardrail let through for one application, with a
 * reason (audited). Listed here so a waiver never lingers unseen.
 */
export function WaiversSection() {
  const qc = useQueryClient()
  const waivers = useQuery({ queryKey: waiversKey, queryFn: listWaivers })
  const rules = useKitList<GuardrailOut>("guardrails").data ?? []
  const apps = useQuery(applicationsQuery()).data?.items ?? []
  const [guardrail, setGuardrail] = useState("")
  const [application, setApplication] = useState("")
  const [reason, setReason] = useState("")

  const refresh = () => qc.invalidateQueries({ queryKey: waiversKey })
  const add = useMutation({
    mutationFn: () =>
      waiveGuardrail(guardrail, {
        application_id: application,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      toast.success("Waived for that application only.")
      setReason("")
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: removeWaiver,
    onSuccess: () => {
      toast.success("Waiver removed. The guardrail applies again.")
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })

  const ruleName = (id: string) =>
    rules.find((g) => g.id === id)?.name ?? "A guardrail"
  const appName = (id: string) => {
    const a = apps.find((x) => x.id === id)
    return a ? `${a.title}, ${a.employer}` : "an application"
  }
  const blocking = rules.filter((g) => g.severity === "block")
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (guardrail && application && reason.trim()) add.mutate()
  }
  const list = waivers.data ?? []

  return (
    <section aria-labelledby="waivers-title" className="grid gap-3">
      <SectionHeader
        as="h3"
        title={<span id="waivers-title">Waivers</span>}
        aside="A guardrail that blocks but may be waived once, let through for one application."
      />
      {list.length === 0 ? (
        <p className="text-sm text-muted-foreground">No waivers.</p>
      ) : (
        <ul className="m-0 grid list-none gap-1.5 p-0" aria-label="Waivers">
          {list.map((w) => (
            <li
              key={w.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-sunken px-3 py-2 text-sm"
            >
              <span className="min-w-0 flex-1">
                <b>{ruleName(w.guardrail_id)}</b> for{" "}
                {appName(w.application_id)}
                <span className="block text-muted-foreground">{w.reason}</span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => remove.mutate(w.id)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        onSubmit={submit}
        aria-label="Waive a guardrail once"
        className="grid gap-2 sm:grid-cols-[1fr_1fr_1.4fr_auto] sm:items-end"
      >
        <div className="grid gap-1">
          <Label htmlFor="waive-rule">Guardrail</Label>
          <select
            id="waive-rule"
            className={SELECT}
            value={guardrail}
            onChange={(e) => setGuardrail(e.target.value)}
          >
            <option value="">Choose</option>
            {blocking.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="waive-app">Application</Label>
          <select
            id="waive-app"
            className={SELECT}
            value={application}
            onChange={(e) => setApplication(e.target.value)}
          >
            <option value="">Choose</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.title}, {a.employer}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="waive-reason">Reason</Label>
          <Input
            id="waive-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why this one application may go out"
          />
        </div>
        <Button
          type="submit"
          variant="outline"
          disabled={
            !guardrail || !application || !reason.trim() || add.isPending
          }
        >
          Waive once
        </Button>
      </form>
    </section>
  )
}
