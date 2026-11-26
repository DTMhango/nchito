import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { SectionHeader } from "@/components/page-header"
import {
  aiKeys,
  pricesQuery,
  replacePrices,
  resetPrices,
  type Price,
  type PriceIn,
} from "./api"

type Row = PriceIn & { key: string }
const RATE_COLUMNS = [
  ["input_per_mtok", "Input"],
  ["output_per_mtok", "Output"],
  ["cache_write_per_mtok", "Cache write"],
  ["cache_read_per_mtok", "Cache read"],
] as const

const toRow = (p: Price): Row => ({
  key: p.id,
  provider: p.provider,
  model: p.model,
  currency: p.currency,
  input_per_mtok: String(Number(p.input_per_mtok)),
  output_per_mtok: String(Number(p.output_per_mtok)),
  cache_write_per_mtok:
    p.cache_write_per_mtok == null
      ? null
      : String(Number(p.cache_write_per_mtok)),
  cache_read_per_mtok:
    p.cache_read_per_mtok == null
      ? null
      : String(Number(p.cache_read_per_mtok)),
  long_context_threshold: p.long_context_threshold,
  long_input_per_mtok: p.long_input_per_mtok,
  long_output_per_mtok: p.long_output_per_mtok,
  as_of: p.as_of,
  source: p.source,
})

/** The price table the ledger estimates and reconciles with: minor units (cents) per million tokens. */
export function PricesSection() {
  const queryClient = useQueryClient()
  const { data } = useQuery(pricesQuery())
  const [rows, setRows] = useState<Row[]>([])
  const [seen, setSeen] = useState<Price[] | undefined>(undefined)
  if (data !== seen) {
    setSeen(data)
    setRows((data ?? []).map(toRow))
  }
  const done = (msg: string) => {
    toast.success(msg)
    void queryClient.invalidateQueries({ queryKey: aiKeys.prices })
  }
  const save = useMutation({
    mutationFn: () => replacePrices(rows.map(({ key, ...r }) => (void key, r))),
    onSuccess: () => done("Price table saved."),
    onError: (e) => toast.error(e.message),
  })
  const reset = useMutation({
    mutationFn: resetPrices,
    onSuccess: () => done("Default prices restored."),
    onError: (e) => toast.error(e.message),
  })
  const edit = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const asOf = data?.[0]?.as_of
  return (
    <section aria-labelledby="ai-prices" className="grid gap-3">
      <SectionHeader
        title={<span id="ai-prices">Price table</span>}
        aside={`Cents per million tokens${asOf ? `; default dated ${asOf}` : ""}. Unpriced models are refused.`}
      />
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Provider</TableHead>
              <TableHead>Model</TableHead>
              {RATE_COLUMNS.map(([, label]) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
              <TableHead>As of</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, i) => (
              <TableRow key={r.key}>
                <TableCell className="text-muted-foreground">
                  {r.provider}
                </TableCell>
                <TableCell className="font-medium">{r.model}</TableCell>
                {RATE_COLUMNS.map(([field, label]) => (
                  <TableCell key={field}>
                    <Input
                      aria-label={`${label} price for ${r.provider} ${r.model}`}
                      inputMode="decimal"
                      className="w-24 num"
                      value={r[field] == null ? "" : String(r[field])}
                      onChange={(e) =>
                        edit(i, {
                          [field]:
                            e.target.value === "" && field.startsWith("cache")
                              ? null
                              : e.target.value,
                          as_of: new Date().toISOString().slice(0, 10),
                        })
                      }
                    />
                  </TableCell>
                ))}
                <TableCell className="num text-faint">{r.as_of}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="flex gap-2">
        <Button disabled={save.isPending} onClick={() => save.mutate()}>
          Save prices
        </Button>
        <Button
          variant="ghost"
          disabled={reset.isPending}
          onClick={() => reset.mutate()}
        >
          Restore defaults
        </Button>
      </div>
    </section>
  )
}
