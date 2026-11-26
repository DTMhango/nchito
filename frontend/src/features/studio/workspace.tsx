import { useEffect, useMemo, useState } from "react"
import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CircleCheck,
  FileText,
  ListChecks,
  Mail,
  RotateCcw,
  Send,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Chip } from "@/components/chip"
import { modKey } from "@/components/key-hint"
import { PageHeader } from "@/components/page-header"
import { ScoreRing } from "@/components/score-ring"
import { StagePill } from "@/components/stage-pill"
import { listQuery } from "@/features/kit/api"
import { meQuery } from "@/lib/api/endpoints"
import { isApiError } from "@/lib/api/client"
import { cn } from "@/lib/utils"
import {
  ACTIVE_RUN,
  applicationQuery,
  createDraftFact,
  jobQuery,
  packetsQuery,
  pendingQuery,
  runQuery,
  sendForApproval,
  startTailoring,
  studioKeys,
  type AnswerOut,
  type ApplicationDetail,
  type ExperienceOut,
  type FactOut,
  type GuardrailOut,
  type TemplateOut,
} from "./api"
import { AnswersPanel } from "./answers-panel"
import { ChecksPanel } from "./checks-panel"
import { claimDomId, type ClaimContext } from "./claims"
import {
  claims as claimsOf,
  groupChecks,
  indexFacts,
  isEmptySpec,
  keywordCoverage,
  limitWarnings,
  needsOwner,
  requirementRows,
  screeningRows,
  traceSummary,
  type ClaimRef,
  type DraftItem,
} from "./draft"
import { JobPane } from "./job-pane"
import { PreviewPane, type PreviewDoc } from "./preview-pane"
import { CvEditor, LetterEditor } from "./spec-editor"
import {
  BudgetPaused,
  NotTailored,
  TailorFailed,
  TailoringProgress,
  runCost,
} from "./states"
import { useDraft } from "./use-draft"
import { useStudioEvents } from "./use-studio-events"

/** How often a live tailoring run is polled when no event arrives (a UI cadence, not a business value). */
export const RUN_POLL_MS = 1500

const SAVE_TEXT = {
  idle: "Saved",
  pending: "Unsaved changes",
  saving: "Saving...",
  saved: "Saved",
  error: "Not saved",
} as const

const TEMPLATE_KEY = "nchito.studio.templates"
function readTemplates(): Partial<Record<"cv" | "letter", string>> {
  try {
    return JSON.parse(localStorage.getItem(TEMPLATE_KEY) ?? "{}")
  } catch {
    return {}
  }
}

/** One application in the Studio: whatever state its tailoring is in. */
export function StudioWorkspace({
  applicationId,
  runId,
  onRun,
}: {
  applicationId: string
  runId: string | undefined
  onRun: (runId: string | undefined) => void
}) {
  const qc = useQueryClient()
  const app = useQuery(applicationQuery(applicationId))
  const run = useQuery(runQuery(runId, RUN_POLL_MS))
  useStudioEvents(applicationId, runId)

  const status = run.data?.status
  useEffect(() => {
    if (status && !ACTIVE_RUN.has(status))
      void qc.invalidateQueries({
        queryKey: studioKeys.application(applicationId),
      })
  }, [status, applicationId, qc])

  const tailor = useMutation({
    mutationFn: () => startTailoring(applicationId),
    onSuccess: (out) => {
      if (out.run_id) onRun(out.run_id)
      void qc.invalidateQueries({
        queryKey: studioKeys.application(applicationId),
      })
    },
  })
  const tailorError = tailor.error
    ? isApiError(tailor.error, 402)
      ? "The AI budget is used up. Raise the cap in Settings › AI, or wait for the new month."
      : tailor.error.message
    : null

  if (app.isPending)
    return (
      <p role="status" className="text-muted-foreground">
        Loading the application...
      </p>
    )
  if (app.isError)
    return (
      <section role="alert" className="grid max-w-[560px] gap-3 panel p-5">
        <h2 className="text-lg">
          {isApiError(app.error, 404)
            ? "This application doesn't exist"
            : "Could not load the application"}
        </h2>
        <p className="text-muted-foreground">
          {isApiError(app.error, 404)
            ? "It may have been merged or removed."
            : app.error.message}
        </p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void app.refetch()}>
            Try again
          </Button>
          <Button asChild variant="ghost">
            <Link to="/studio" search={{}}>
              Choose another application
            </Link>
          </Button>
        </div>
      </section>
    )

  const a = app.data
  const r = run.data
  const live = (r && ACTIVE_RUN.has(r.status)) || (runId && run.isPending)
  const finishing =
    r?.status === "succeeded" && isEmptySpec(a.spec) && app.isFetching
  const retry = () => tailor.mutate()

  let body
  if (live || finishing) body = <TailoringProgress run={r} />
  else if (r?.status === "paused")
    body = <BudgetPaused run={r} onRetry={retry} retrying={tailor.isPending} />
  else if (r?.status === "failed")
    body = <TailorFailed run={r} onRetry={retry} retrying={tailor.isPending} />
  else if (isEmptySpec(a.spec))
    body = (
      <NotTailored
        onTailor={retry}
        pending={tailor.isPending}
        error={tailorError}
      />
    )
  else body = <Editor key={a.id} app={a} onRetailor={retry} />

  return (
    <div>
      <PageHeader
        eyebrow={<>Studio · {a.employer}</>}
        title={
          <span className="inline-flex items-center gap-3">
            {a.score != null && <ScoreRing score={a.score} size={40} />}
            {a.title}
          </span>
        }
        meta={
          <>
            <StagePill stage={a.stage} />
            {r && !live && (
              <Chip tone="line" data-testid="tailor-cost-chip">
                Tailoring cost {runCost(r)}
              </Chip>
            )}
          </>
        }
        actions={
          <Button asChild size="sm" variant="ghost">
            <Link
              to="/jobs/$id"
              params={{ id: a.job_id }}
              search={{ tab: "documents" }}
            >
              Job page
            </Link>
          </Button>
        }
      />
      {body}
    </div>
  )
}

function Editor({
  app,
  onRetailor,
}: {
  app: ApplicationDetail
  onRetailor: () => void
}) {
  const qc = useQueryClient()
  const d = useDraft(app)
  const job = useQuery(jobQuery(app.job_id))
  const facts = useQuery(listQuery<FactOut>("facts"))
  const guardrails = useQuery(listQuery<GuardrailOut>("guardrails"))
  const templates = useQuery(listQuery<TemplateOut>("templates"))
  const bank = useQuery(listQuery<AnswerOut>("answers"))
  const experiences = useQuery(listQuery<ExperienceOut>("experiences"))
  const packets = useQuery(packetsQuery(app.id))
  const pending = useQuery(pendingQuery())
  const me = useQuery(meQuery())
  const [tab, setTab] = useState<PreviewDoc>("cv")
  const [templateKey, setTemplateKey] = useState(readTemplates)
  const [adding, setAdding] = useState<string | null>(null)

  const index = useMemo(() => indexFacts(facts.data ?? []), [facts.data])
  const claimRefs = claimsOf(d.draft)
  const trace = traceSummary(d.draft, index)
  const rows = requirementRows(job.data, d.draft.requirement_match)
  const keywords = keywordCoverage(job.data, d.draft)
  const tmpl = templates.data ?? []
  const pick = (kind: "cv" | "letter") =>
    tmpl.find((t) => t.kind === kind && t.key === templateKey[kind]) ??
    tmpl.find((t) => t.kind === kind)
  const warnings = limitWarnings(d.draft, pick("cv"), pick("letter"))
  const latest = [...(packets.data ?? [])].sort(
    (x, y) => y.version - x.version
  )[0]
  const today = new Date().toISOString().slice(0, 10)
  const answers = screeningRows(
    latest?.contents.answers ?? [],
    bank.data ?? [],
    pending.data ?? [],
    app.id,
    today
  )
  const groups = groupChecks(d.results)
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

  const approve = useMutation({
    mutationFn: async () => {
      await d.flush()
      return sendForApproval(app.id)
    },
    onSuccess: (out) => {
      qc.setQueryData(studioKeys.application(app.id), {
        ...app,
        ...out,
        spec: app.spec,
        check_results: d.results,
      })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      toast.success("Sent for approval. It waits for you in Autopilot.")
    },
    onError: (e) => toast.error(e.message),
  })

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

  const blockers: string[] = []
  if (d.checkState === "unchecked") blockers.push("Run the checks first.")
  if (d.checkState === "stale") blockers.push("Re-check after your edits.")
  if (groups.block.length)
    blockers.push(
      `${groups.block.length} check${groups.block.length === 1 ? "" : "s"} block${groups.block.length === 1 ? "s" : ""} sending.`
    )
  if (openAnswers)
    blockers.push(
      `${openAnswers} question${openAnswers === 1 ? "" : "s"} need${openAnswers === 1 ? "s" : ""} your answer.`
    )
  const canSend = app.allowed_next?.includes("ready") ?? false
  const waiting = app.stage === "ready"

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
        {d.saveError && <span className="text-danger">{d.saveError}</span>}
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
            <AnswersPanel
              rows={answers}
              loading={packets.isPending || bank.isPending}
            />
          </TabsContent>
        </Tabs>

        <div className="grid min-w-0 gap-5 lg:col-span-2 xl:sticky xl:top-2 xl:col-span-1">
          <ChecksPanel
            applicationId={app.id}
            results={d.results}
            guardrails={guardrails.data ?? []}
            checkState={d.checkState}
            rechecking={d.recheck.isPending}
            onRecheck={() => d.recheck.mutate()}
            claims={claimRefs}
            index={index}
            onFocusClaim={focusClaim}
            onWaived={() => d.recheck.mutate()}
          />
          <PreviewPane
            doc={tab}
            draft={d.draft}
            owner={me.data?.display_name ?? "Your name"}
            experiences={experiences.data ?? []}
            templates={tmpl}
            templateKey={templateKey}
            onTemplate={(kind, key) => {
              const next = { ...templateKey, [kind]: key }
              setTemplateKey(next)
              try {
                localStorage.setItem(TEMPLATE_KEY, JSON.stringify(next))
              } catch {
                // The choice lasts for this visit only.
              }
            }}
            warnings={warnings}
            limitResults={d.results.filter((x) => x.check === "limit")}
            answers={answers}
            applicationId={app.id}
            beforeDownload={d.flush}
            saving={d.saveState === "pending" || d.saveState === "saving"}
          />
        </div>
      </div>

      <div
        role="region"
        aria-label="Checks summary"
        className="sticky bottom-0 z-10 mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 elev px-4 py-3"
      >
        <Metric
          label="Facts traced"
          value={`${trace.traced}/${trace.total}`}
          ok={trace.flagged === 0}
        />
        <Metric
          label="Guardrails"
          value={
            groups.block.length
              ? `${groups.block.length} blocking`
              : groups.warn.length
                ? `${groups.warn.length} to review`
                : "Clear"
          }
          ok={groups.block.length === 0}
        />
        <Metric
          label="Keywords"
          value={`${keywords.filter((k) => k.covered).length}/${keywords.length}`}
          ok={keywords.every((k) => k.covered)}
        />
        <Metric
          label="Answers"
          value={openAnswers ? `${openAnswers} need you` : "Ready"}
          ok={openAnswers === 0}
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {waiting ? (
            <>
              <Chip tone="primary" icon={CircleCheck}>
                Waiting for your approval
              </Chip>
              <Button asChild size="sm">
                <Link to="/autopilot">Open the approval</Link>
              </Button>
            </>
          ) : (
            <>
              {blockers.length > 0 && (
                <span
                  id="send-blockers"
                  className="max-w-[36ch] text-sm text-muted-foreground"
                >
                  {blockers[0]}
                </span>
              )}
              <Button
                disabled={!canSend || blockers.length > 0 || approve.isPending}
                aria-describedby={blockers.length ? "send-blockers" : undefined}
                onClick={() => approve.mutate()}
              >
                <Send aria-hidden="true" />
                Send for approval
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  ok,
}: {
  label: string
  value: string
  ok: boolean
}) {
  return (
    <div className="grid gap-px">
      <span className="eyebrow">{label}</span>
      <span
        className={cn(
          "num font-semibold",
          ok ? "text-foreground" : "text-warn"
        )}
      >
        {value}
      </span>
    </div>
  )
}

/** Apply `fn` to the draft item with this key, wherever it sits. */
function withItem(
  d: ReturnType<typeof useDraft>["draft"],
  key: string,
  fn: (it: DraftItem) => DraftItem
) {
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
