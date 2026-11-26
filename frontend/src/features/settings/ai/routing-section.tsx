import { costOf } from "@/lib/cost"
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import {
  activateRoute,
  aiKeys,
  pricesQuery,
  routingQuery,
  stageLabel,
  testRoute,
  type Route,
} from "./api"

/** Model per stage. A new model is tested with one tiny request before it can be activated. */
export function RoutingSection() {
  const { data: routes = [] } = useQuery(routingQuery())
  const { data: prices = [] } = useQuery(pricesQuery())
  const models = [...new Set(prices.map((p) => p.model))]
  return (
    <section aria-labelledby="ai-routing" className="grid gap-3">
      <SectionHeader
        title={<span id="ai-routing">Model per stage</span>}
        aside="Test a route, then activate it. Tests cost a fraction of a cent."
      />
      <datalist id="ai-models">
        {models.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>
      <div className="grid gap-2" role="list" aria-label="Stages">
        {routes.map((r) => (
          <RouteRow key={r.stage} route={r} />
        ))}
      </div>
    </section>
  )
}

function RouteRow({ route }: { route: Route }) {
  const queryClient = useQueryClient()
  const [model, setModel] = useState(route.model)
  const [testedOk, setTestedOk] = useState<string | null>(null)
  const changed = model.trim() !== route.model
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: aiKeys.routing })
    void queryClient.invalidateQueries({ queryKey: aiKeys.spend })
  }
  const test = useMutation({
    mutationFn: () => testRoute(route.stage, model.trim()),
    onSuccess: (r) => {
      if (r.ok) {
        setTestedOk(r.model ?? model.trim())
        toast.success(
          `${stageLabel(route.stage)}: ${r.model} works (${costOf(r, "cost", { currency: r.currency ?? "USD" })}).`
        )
      } else toast.error(r.detail ?? "The test failed.")
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const activate = useMutation({
    mutationFn: () => activateRoute(route.stage, model.trim()),
    onSuccess: (r) => {
      toast.success(`${stageLabel(r.stage)} now uses ${r.model}.`)
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const last = route.last_test
  return (
    <div
      role="listitem"
      className="grid items-center gap-x-3 gap-y-1.5 rounded-md border border-border bg-surface row-pad sm:grid-cols-[150px_minmax(0,1fr)_auto]"
    >
      <span className="font-semibold">{stageLabel(route.stage)}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Input
          aria-label={`Model for ${stageLabel(route.stage)}`}
          list="ai-models"
          className="max-w-[260px]"
          value={model}
          onChange={(e) => {
            setModel(e.target.value)
            setTestedOk(null)
          }}
        />
        {!route.billed && <Chip tone="info">Not billed</Chip>}
        {last && !changed && (
          <Chip tone={last.ok ? "good" : "danger"}>
            {last.ok ? "Tested" : "Test failed"}
          </Chip>
        )}
      </div>
      <span className="flex gap-1.5">
        <Button
          size="sm"
          variant="outline"
          disabled={test.isPending || !model.trim()}
          onClick={() => test.mutate()}
        >
          Test
        </Button>
        {changed && (
          <Button
            size="sm"
            disabled={activate.isPending || testedOk !== model.trim()}
            onClick={() => activate.mutate()}
          >
            Activate
          </Button>
        )}
      </span>
    </div>
  )
}
