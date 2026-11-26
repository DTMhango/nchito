import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Segmented } from "@/components/segmented"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  backfillCustomFacet,
  createCustomFacet,
  createTagRule,
  customFacetsQuery,
  deleteCustomFacet,
  deleteTagRule,
  invalidateJobs,
  jobCountQuery,
  mkeys,
  tagRulesQuery,
} from "./api"
import { FacetPanel, type FacetSels } from "./facet-controls"
import { fromConditionSet, summarise, toConditionSet } from "./filters"
import { plural } from "./format"
import type {
  BackfillEstimate,
  CustomFacetOut,
  FacetCatalogEntry,
} from "./types"

const errText = (e: unknown, fallback: string) =>
  e instanceof Error ? e.message : fallback

type Tab = "rules" | "questions"

/** Rule tags ("when ... then tag ...") and custom yes/no questions (DESIGN 6.1). */
export function TagsManager({
  open,
  onOpenChange,
  catalog,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  catalog: FacetCatalogEntry[]
}) {
  const [tab, setTab] = useState<Tab>("rules")
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] gap-4 overflow-y-auto pop-surface p-5 sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">
            Rule tags and questions
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            Rule tags label every new job that matches, for free. Questions are
            answered yes, no or not stated by a small model and become facets
            you can filter on.
          </DialogDescription>
        </DialogHeader>
        <Segmented<Tab>
          aria-label="Manage"
          value={tab}
          onValueChange={setTab}
          options={[
            { value: "rules", label: "Rule tags" },
            { value: "questions", label: "Questions" },
          ]}
        />
        {tab === "rules" ? <RuleTags catalog={catalog} /> : <Questions />}
      </DialogContent>
    </Dialog>
  )
}

function RuleTags({ catalog }: { catalog: FacetCatalogEntry[] }) {
  const qc = useQueryClient()
  const id = useId()
  const rules = useQuery(tagRulesQuery())
  const [building, setBuilding] = useState(false)
  const [tag, setTag] = useState("")
  const [sels, setSels] = useState<FacetSels>({})
  const conditions = toConditionSet(sels)
  const hasConditions = conditions.root.conditions.length > 0
  const count = useQuery({
    ...jobCountQuery({ conditions }),
    enabled: building && hasConditions,
  })
  const create = useMutation({
    mutationFn: () =>
      createTagRule({
        tag: tag.trim().toLowerCase(),
        conditions: conditions as never,
        enabled: true,
      }),
    onSuccess: (r) => {
      toast.success(`Rule tag “${r.tag}” saved`)
      setBuilding(false)
      setTag("")
      setSels({})
      void qc.invalidateQueries({ queryKey: mkeys.tagRules })
      invalidateJobs(qc)
    },
    onError: (e) => toast.error(errText(e, "Could not save the rule.")),
  })
  const del = useMutation({
    mutationFn: (rid: string) => deleteTagRule(rid),
    onSuccess: () => qc.invalidateQueries({ queryKey: mkeys.tagRules }),
  })
  // The builder hides tags as a facet: a rule tag built on tags would loop.
  const builderCatalog = catalog.filter((c) => c.facet !== "tags")

  return (
    <div className="grid gap-3">
      <ul className="grid border-t border-border">
        {(rules.data?.items ?? []).map((r) => (
          <li
            key={r.id}
            className="flex items-start gap-3 border-b border-border py-2 text-sm"
          >
            <span className="rounded-full bg-highlight-soft px-2 py-0.5 text-[0.78rem] font-medium text-highlight-ink">
              {r.tag}
            </span>
            <span className="min-w-0 flex-1 text-muted-foreground">
              When:{" "}
              {summarise(fromConditionSet(r.conditions), catalog) || "any job"}
            </span>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={`Delete rule tag ${r.tag}`}
              onClick={() => del.mutate(r.id)}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
        {rules.data?.items.length === 0 && (
          <li className="py-3 text-sm text-muted-foreground">
            No rule tags yet.
          </li>
        )}
      </ul>
      {building ? (
        <form
          className="grid gap-3 rounded-md border border-border p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (tag.trim() && hasConditions) create.mutate()
          }}
        >
          <div className="grid gap-1.5">
            <label htmlFor={id} className="eyebrow">
              Then tag
            </label>
            <Input
              id={id}
              autoFocus
              value={tag}
              onChange={(e) => setTag(e.target.value)}
            />
          </div>
          <div className="eyebrow">When</div>
          <div className="max-h-[38dvh] overflow-y-auto pr-1">
            <FacetPanel
              catalog={builderCatalog}
              sels={sels}
              onChange={setSels}
              hideCounts
            />
          </div>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {hasConditions
              ? `${summarise(sels, catalog)}. ${count.data != null ? `Matches ${plural(count.data, "saved job")} now.` : ""}`
              : "Pick at least one value."}
          </p>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setBuilding(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!tag.trim() || !hasConditions || create.isPending}
            >
              Save rule tag
            </Button>
          </div>
        </form>
      ) : (
        <Button
          variant="outline"
          className="w-fit"
          onClick={() => setBuilding(true)}
        >
          <Plus data-icon="inline-start" aria-hidden="true" />
          New rule tag
        </Button>
      )}
    </div>
  )
}

const slug = (q: string) =>
  q
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48)

function money(e: BackfillEstimate) {
  return new Intl.NumberFormat("en", {
    style: "currency",
    currency: e.currency,
  }).format(e.estimated_cost_minor / 100)
}

function Questions() {
  const qc = useQueryClient()
  const id = useId()
  const list = useQuery(customFacetsQuery())
  const [question, setQuestion] = useState("")
  const [pending, setPending] = useState<{
    facet: CustomFacetOut
    estimate: BackfillEstimate
  } | null>(null)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: mkeys.customFacets })
    void qc.invalidateQueries({ queryKey: mkeys.facets })
  }
  const create = useMutation({
    mutationFn: async () => {
      const facet = await createCustomFacet({
        key: slug(question),
        question: question.trim(),
        enabled: true,
      })
      const estimate = await backfillCustomFacet(facet.id, false)
      return { facet, estimate }
    },
    onSuccess: (res) => {
      setQuestion("")
      setPending(res)
      refresh()
    },
    onError: (e) => toast.error(errText(e, "Could not add the question.")),
  })
  const backfill = useMutation({
    mutationFn: (fid: string) => backfillCustomFacet(fid, true),
    onSuccess: (e) => {
      toast.success(
        `Answering it for ${plural(e.jobs, "saved job")}. Answers appear as they arrive.`
      )
      setPending(null)
      refresh()
      invalidateJobs(qc)
    },
    onError: (e) => toast.error(errText(e, "Backfill did not start.")),
  })
  const del = useMutation({
    mutationFn: (fid: string) => deleteCustomFacet(fid),
    onSuccess: refresh,
  })

  return (
    <div className="grid gap-3">
      <ul className="grid border-t border-border">
        {(list.data?.items ?? []).map((c) => (
          <li
            key={c.id}
            className="flex items-start gap-3 border-b border-border py-2 text-sm"
          >
            <span className="min-w-0 flex-1">{c.question}</span>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={`Delete question: ${c.question}`}
              onClick={() => del.mutate(c.id)}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
        {list.data?.items.length === 0 && (
          <li className="py-3 text-sm text-muted-foreground">
            No questions yet.
          </li>
        )}
      </ul>

      {pending ? (
        <div
          className="grid gap-3 rounded-md border border-border p-3"
          aria-live="polite"
        >
          <p className="text-sm">
            New jobs will be asked “{pending.facet.question}”. Answering it for
            the {plural(pending.estimate.jobs, "saved job")} you have now costs
            about <b className="num">{money(pending.estimate)}</b>, within the
            budget cap.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setPending(null)}>
              New jobs only
            </Button>
            <Button
              onClick={() => backfill.mutate(pending.facet.id)}
              disabled={backfill.isPending}
            >
              Answer for saved jobs too
            </Button>
          </div>
        </div>
      ) : (
        <form
          className="grid gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (question.trim()) create.mutate()
          }}
        >
          <label htmlFor={id} className="eyebrow">
            New yes/no question
          </label>
          <Textarea
            id={id}
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Does the role require RMS or Verisk experience?"
          />
          <Button
            type="submit"
            variant="outline"
            className="w-fit"
            disabled={!question.trim() || create.isPending}
          >
            Add question and see the cost
          </Button>
        </form>
      )}
    </div>
  )
}
