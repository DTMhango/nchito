import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileText, ListChecks, Mail, RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Chip } from "@/components/chip"
import { modKey } from "@/components/key-hint"
import { listQuery } from "@/features/kit/api"
import { meQuery } from "@/lib/api/endpoints"
import {
  createDraftFact,
  documentTemplatesQuery,
  jobQuery,
  type ApplicationDetail,
  type ExperienceOut,
  type FactOut,
  type GuardrailOut,
  type RenderKind,
  type SpecState,
} from "./api"
import { AnswersPanel } from "./answers-panel"
import { ChecksPanel } from "./checks-panel"
import { claimDomId, type ClaimContext } from "./claims"
import {
  claims as claimsOf,
  indexFacts,
  keywordCoverage,
  needsOwner,
  requirementRows,
  screeningRows,
  type ClaimRef,
  type Draft,
  type DraftItem,
} from "./draft"
import { JobPane } from "./job-pane"
import { PreviewPane, type PreviewDoc } from "./preview-pane"
import { SendBar } from "./send-bar"
import { CvEditor, LetterEditor } from "./spec-editor"
import { defaultTemplate } from "./templates"
import { useDraft } from "./use-draft"

const SAVE_TEXT = {
  idle: "Saved",
  pending: "Unsaved changes",
  saving: "Saving...",
  saved: "Saved",
  error: "Not saved",
} as const

export function Editor({
  app,
  state,
  onRetailor,
}: {
  app: ApplicationDetail
  state: SpecState
  onRetailor: () => void
}) {
  const qc = useQueryClient()
  const d = useDraft(app.id, state)
  const job = useQuery(jobQuery(app.job_id))
  const facts = useQuery(listQuery<FactOut>("facts"))
  const guardrails = useQuery(listQuery<GuardrailOut>("guardrails"))
  const templates = useQuery(documentTemplatesQuery(app.id))
  const experiences = useQuery(listQuery<ExperienceOut>("experiences"))
  const me = useQuery(meQuery())
  const defaults = {
    cv: defaultTemplate("cv", templates.data),
    letter: defaultTemplate("letter", templates.data),
  }
  const [tab, setTab] = useState<PreviewDoc>("cv")
  const [picked, setPicked] = useState<Partial<Record<RenderKind, string>>>({})
  const [adding, setAdding] = useState<string | null>(null)
  // Until the server's list arrives nothing is picked: the server's own default applies.
  const chosen = {
    cv: picked.cv ?? defaults.cv?.key ?? "",
    letter: picked.letter ?? defaults.letter?.key ?? "",
  }

  const index = useMemo(() => indexFacts(facts.data ?? []), [facts.data])
  const claimRefs = claimsOf(d.draft)
  const rows = requirementRows(job.data, d.draft.requirement_match)
  const keywords = keywordCoverage(job.data, d.draft)
  const answers = screeningRows(state.answers)
  const openAnswers = answers.filter(needsOwner).length

  const addToLibrary = useMutation({
    mutationFn: (item: DraftItem) =>
      createDraftFact({ kind: "bullet", text: item.text.trim() }),
    onMutate: (item) => setAdding(item.key),
    onSettled: () => setAdding(null),
    onSuccess: (fact, item) => {
      void qc.invalidateQueries({ queryKey: ["kit", "facts"] })
      d.setDraft((x) =>
        withItem(x, item.key, (it) => ({
          ...it,
          fact_ids: [...it.fact_ids, fact.id],
        }))
      )
      toast.success(
        `Added to your library as draft ${fact.code}. Approve it in Kit › Library and this claim is traced.`
      )
    },
    onError: (e) => toast.error(e.message),
  })

  const ctx: ClaimContext = {
    index,
    citable: (facts.data ?? []).filter((f) => f.status === "approved"),
    onAddToLibrary: (item) => addToLibrary.mutate(item),
    addingKey: adding,
  }

  const { recheck, flush } = d
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      if (e.key === "s") {
        e.preventDefault()
        void flush()
      } else if (e.key === "Enter") {
        e.preventDefault()
        if (!recheck.isPending) recheck.mutate()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [flush, recheck])

  const focusClaim = (c: ClaimRef) => {
    setTab(c.doc)
    requestAnimationFrame(() =>
      document.getElementById(claimDomId(c.item.key))?.focus()
    )
  }
  const saving = d.saveState === "pending" || d.saveState === "saving"

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <Chip
          tone={d.saveState === "error" ? "danger" : "line"}
          aria-live="polite"
          data-testid="save-state"
        >
          {SAVE_TEXT[d.saveState]}
        </Chip>
        {d.saveError && (
          <span role="alert" className="text-danger">
            {d.saveError}
          </span>
        )}
        <span className="text-faint">
          Autosaves as you type · {modKey()} S saves now · {modKey()} Enter
          re-checks
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={onRetailor}
        >
          <RotateCcw aria-hidden="true" />
          Tailor again
        </Button>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)_minmax(320px,420px)]">
        <JobPane job={job.data} rows={rows} keywords={keywords} index={index} />

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as PreviewDoc)}
          className="min-w-0"
        >
          <TabsList variant="line" aria-label="Documents">
            <TabsTrigger value="cv">
              <FileText aria-hidden="true" />
              CV
            </TabsTrigger>
            <TabsTrigger value="letter">
              <Mail aria-hidden="true" />
              Cover letter
            </TabsTrigger>
            <TabsTrigger value="answers">
              <ListChecks aria-hidden="true" />
              Screening answers
              {openAnswers > 0 && (
                <span className="rounded-full bg-info-soft px-1.5 num text-[0.7rem] text-info">
                  {openAnswers}
                </span>
              )}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="cv" className="pt-3">
            <CvEditor
              draft={d.draft}
              edit={d.setDraft}
              ctx={ctx}
              experiences={experiences.data ?? []}
            />
          </TabsContent>
          <TabsContent value="letter" className="pt-3">
            <LetterEditor draft={d.draft} edit={d.setDraft} ctx={ctx} />
          </TabsContent>
          <TabsContent value="answers" className="pt-3">
            <AnswersPanel rows={answers} loading={false} />
          </TabsContent>
        </Tabs>

        <div className="grid min-w-0 gap-5 lg:col-span-2 xl:sticky xl:top-2 xl:col-span-1">
          <ChecksPanel
            applicationId={app.id}
            results={d.results}
            guardrails={guardrails.data ?? []}
            checkState={d.checkState}
            staleReasons={d.staleReasons}
            rechecking={d.recheck.isPending}
            onRecheck={() => d.recheck.mutate()}
            claims={claimRefs}
            index={index}
            onFocusClaim={focusClaim}
            onWaived={() => d.recheck.mutate()}
          />
          {d.recheckError && (
            <p role="alert" className="text-sm text-danger">
              {d.recheckError}
            </p>
          )}
          <PreviewPane
            doc={tab}
            draft={d.draft}
            owner={me.data?.display_name ?? "Your name"}
            experiences={experiences.data ?? []}
            templates={templates.data}
            chosen={chosen}
            defaults={defaults}
            onTemplate={(kind, key) =>
              setPicked((p) => ({ ...p, [kind]: key }))
            }
            answers={answers}
            applicationId={app.id}
            contentHash={state.content_hash}
            beforeDownload={d.flush}
            saving={saving}
          />
        </div>
      </div>

      <SendBar
        app={app}
        job={job.data}
        draft={d}
        index={index}
        keywords={keywords}
        answers={answers}
        templates={chosen}
        onOpenAnswers={() => setTab("answers")}
      />
    </div>
  )
}

/** Apply `fn` to the draft item with this key, wherever it sits. */
function withItem(d: Draft, key: string, fn: (it: DraftItem) => DraftItem) {
  const one = (it: DraftItem | null) => (it && it.key === key ? fn(it) : it)
  const many = (xs: DraftItem[]) => xs.map((x) => (x.key === key ? fn(x) : x))
  return {
    ...d,
    headline: one(d.headline),
    summary: one(d.summary),
    competencies: many(d.competencies),
    experience: d.experience.map((e) => ({ ...e, bullets: many(e.bullets) })),
    letter: many(d.letter),
  }
}
