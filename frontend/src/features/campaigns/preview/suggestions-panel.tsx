import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Info } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  analyse,
  openSuggestionsQuery,
  pk,
  summaryQuery,
  type OwnerOnlyNote,
} from "./api"
import { SuggestionCard } from "./suggestion-card"

/** Thumbs so far, "Analyse now", owner-only notes and the open suggestions for one campaign. */
export function SuggestionsPanel({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient()
  const summary = useQuery(summaryQuery(campaignId))
  const list = useQuery(openSuggestionsQuery(campaignId))
  const refresh = () => qc.invalidateQueries({ queryKey: pk.all })
  const run = useMutation({
    mutationFn: () => analyse(campaignId),
    onSuccess: async (r) => {
      await refresh()
      toast.success(
        r.created.length === 0
          ? "Nothing new to suggest yet."
          : `${r.created.length} new ${r.created.length === 1 ? "suggestion" : "suggestions"}.`
      )
    },
    onError: (e) => toast.error(e.message),
  })
  const s = summary.data
  const items = list.data ?? []
  // Notes from the last analysis win over the summary's (they are the newer reading).
  const ownerOnly: OwnerOnlyNote[] = run.data?.owner_only ?? s?.owner_only ?? []

  return (
    <section aria-label="Suggestions from your feedback" className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-sm" aria-live="polite">
          {s ? (
            <>
              <b className="num">{s.up}</b> thumbs up,{" "}
              <b className="num">{s.down}</b> thumbs down,{" "}
              <b className="num">{s.open_suggestions}</b> open{" "}
              {s.open_suggestions === 1 ? "suggestion" : "suggestions"}.{" "}
              <span className="text-muted-foreground">
                {s.last_analysed_at
                  ? `Last analysed ${new Date(s.last_analysed_at).toLocaleString()}.`
                  : "Not analysed yet."}
              </span>
            </>
          ) : (
            <span className="text-muted-foreground">Loading.</span>
          )}
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={run.isPending}
          onClick={() => run.mutate()}
        >
          {run.isPending ? "Analysing…" : "Analyse now"}
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">
        Suggestions come only from your thumbs and outcomes. Nothing changes
        until you accept one, and each shows what it would have done first.
      </p>

      {ownerOnly.length > 0 && (
        <div
          role="note"
          className="grid gap-1 rounded-md border border-border bg-info-soft p-2.5 text-sm text-info"
        >
          <p className="flex items-start gap-2 font-medium">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            Suggestions never change seniority, countries, pay floors or your
            eligibility answers. Those are yours to set:
          </p>
          <ul className="list-disc pl-8">
            {ownerOnly.map((n) => (
              <li key={n.area}>{n.message}</li>
            ))}
          </ul>
        </div>
      )}

      {list.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading suggestions.</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No open suggestions. Give a few roles a thumb, then analyse.
        </p>
      ) : (
        <ul aria-label="Open suggestions" className="grid gap-3">
          {items.map((it) => (
            <li key={it.id}>
              <SuggestionCard suggestion={it} onDecided={refresh} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
