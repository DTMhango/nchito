import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  CircleHelp,
  History,
  Printer,
  RefreshCw,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import type { FactIndex } from "@/features/studio/draft"
import { dateText } from "../format"
import {
  editSection,
  packKeys,
  refusalCode,
  regenerateSection,
  saveNote,
  versionsQuery,
} from "./api"
import { ClaimView } from "./claim-view"
import {
  CODE_SECTIONS,
  sectionTitle,
  type Claim,
  type CribSheet,
  type Gaps,
  type PackSection,
  type PaySheet,
  type Questions,
  type QuestionsToAsk,
  type RoleBrief,
  type Stories,
  type WhyYou,
} from "./shapes"
import { StoryCard } from "./story"

const QUESTION_ORDER = [
  "behavioural",
  "technical",
  "role",
  "motivation",
  "logistics",
]

const PAY_STATUS: Record<PaySheet["lines"][number]["status"], string> = {
  confirmed: "Your confirmed answer",
  told_them: "What you told them",
  not_disclosed: "Not disclosed",
  decide: "Decide",
}

/** A copy of `content` with the claim at `path` reworded. */
function withClaimText(
  content: Record<string, unknown>,
  path: (string | number)[],
  text: string
): Record<string, unknown> {
  const next = structuredClone(content)
  let node: unknown = next
  for (const p of path) node = (node as Record<string | number, unknown>)[p]
  ;(node as Claim).text = text
  return next
}

type BodyProps = {
  jobId: string
  sectionKey: string
  section: PackSection
  index: FactIndex
  locked: boolean
  busy: boolean
  editClaim: (path: (string | number)[], text: string) => void
}

const List = ({ items, label }: { items: string[]; label: string }) =>
  items.length ? (
    <div className="grid gap-1">
      <h4 className="eyebrow">{label}</h4>
      <ul className="m-0 grid list-disc gap-0.5 pl-5 text-sm">
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </div>
  ) : null

function Body(p: BodyProps) {
  const { section, index, sectionKey: key } = p
  const c = section.content
  const claim = (
    id: string,
    cl: Claim,
    path: (string | number)[],
    lead?: string,
    detail?: string
  ) => (
    <ClaimView
      key={id}
      id={id}
      claim={cl}
      index={index}
      lead={lead}
      detail={detail}
      saving={p.busy}
      onSave={p.locked ? undefined : (t) => p.editClaim(path, t)}
    />
  )

  switch (key) {
    case "role_brief": {
      const r = c as unknown as RoleBrief
      return (
        <div className="grid gap-3">
          {r.posting_changed && (
            <p role="alert" className="text-sm font-semibold text-warn">
              The posting changed after you applied: this brief reads the
              current posting.
            </p>
          )}
          {r.summary && <p className="whitespace-pre-wrap">{r.summary}</p>}
          <List label="What the posting stresses" items={r.emphasised} />
          <List label="What it asks for" items={r.requirements} />
          {r.level_notes && <p className="text-sm">{r.level_notes}</p>}
          <List label="About the employer" items={r.company_notes} />
          {r.research_note && (
            <p className="text-xs text-muted-foreground">{r.research_note}</p>
          )}
        </div>
      )
    }
    case "why_you": {
      const w = c as unknown as WhyYou
      return (
        <ul className="m-0 grid list-none gap-2 p-0">
          {w.points.map((pt, i) =>
            claim(
              `why_you.${i}`,
              pt.point,
              ["points", i, "point"],
              pt.requirement || undefined
            )
          )}
        </ul>
      )
    }
    case "questions": {
      const q = c as unknown as Questions
      const cats = [
        ...QUESTION_ORDER,
        ...q.items.map((i) => i.category),
      ].filter((x, i, a) => a.indexOf(x) === i)
      return (
        <div className="grid gap-4">
          {cats.map((cat) => {
            const items = q.items
              .map((it, i) => ({ it, i }))
              .filter(({ it }) => it.category === cat)
            if (!items.length) return null
            return (
              <div key={cat} className="grid gap-2">
                <h4 className="eyebrow capitalize">{cat}</h4>
                <ul className="m-0 grid list-none gap-2 p-0">
                  {items.map(({ it, i }) =>
                    claim(
                      `questions.${i}`,
                      it.answer,
                      ["items", i, "answer"],
                      it.question,
                      it.why_asked
                    )
                  )}
                </ul>
              </div>
            )
          })}
        </div>
      )
    }
    case "stories": {
      const s = c as unknown as Stories
      const sorted = [...s.items].sort(
        (a, b) => Number(b.favourite) - Number(a.favourite)
      )
      return (
        <ul className="m-0 grid list-none gap-2 p-0">
          {sorted.map((st) => (
            <StoryCard
              key={st.id}
              jobId={p.jobId}
              story={st}
              index={index}
              baseVersion={section.version}
              locked={p.locked}
            />
          ))}
        </ul>
      )
    }
    case "questions_to_ask": {
      const q = c as unknown as QuestionsToAsk
      return (
        <ul className="m-0 grid list-none gap-2 p-0">
          {q.items.map((it) => (
            <li
              key={it.question}
              className="grid gap-0.5 rounded-md border border-border bg-surface p-3"
            >
              <span className="font-semibold">{it.question}</span>
              {it.why && (
                <span className="text-xs text-muted-foreground">{it.why}</span>
              )}
            </li>
          ))}
        </ul>
      )
    }
    case "gaps": {
      const g = c as unknown as Gaps
      return (
        <ul className="m-0 grid list-none gap-2 p-0">
          {g.items.map((it, i) =>
            claim(
              `gaps.${i}`,
              it.answer,
              ["items", i, "answer"],
              it.requirement,
              it.gap
            )
          )}
        </ul>
      )
    }
    case "pay_sheet": {
      const ps = c as unknown as PaySheet
      return (
        <div className="grid gap-2">
          <p className="text-sm">
            <b>Pay in the posting: </b>
            {ps.posting_pay ?? (
              <span className="text-muted-foreground italic">Not stated</span>
            )}
          </p>
          <ul className="m-0 grid list-none gap-2 p-0">
            {ps.lines.map((l) => {
              const value =
                l.status === "confirmed"
                  ? l.kit_answer
                  : l.status === "told_them"
                    ? l.told_them
                    : null
              return (
                <li
                  key={l.topic}
                  data-pay-line={l.topic}
                  data-state={l.status}
                  className="grid gap-1 rounded-md border border-border bg-surface p-3 sm:grid-cols-[14rem_1fr] sm:items-center"
                >
                  <span className="grid">
                    <span className="font-semibold">{l.topic}</span>
                    <span className="text-xs text-muted-foreground">
                      {l.question}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5">
                    {value ? (
                      <>
                        <span className="eyebrow">{PAY_STATUS[l.status]}</span>
                        <span>{value}</span>
                      </>
                    ) : (
                      <Chip
                        tone={l.status === "decide" ? "warn" : "line"}
                        icon={CircleHelp}
                      >
                        {PAY_STATUS[l.status]}
                      </Chip>
                    )}
                    {l.note && <span className="text-sm">{l.note}</span>}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      )
    }
    case "crib_sheet": {
      const cs = c as unknown as CribSheet
      return (
        <div id="crib-print" className="grid gap-2">
          {cs.role && <p className="font-semibold">{cs.role}</p>}
          <List label="Points" items={cs.points} />
          <List label="Stories" items={cs.stories} />
          <List label="Questions to ask" items={cs.questions_to_ask} />
          <List label="Pay" items={cs.pay} />
          <List label="Gaps" items={cs.gaps} />
          {cs.flagged.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Left out because they failed the truth checks:{" "}
              {cs.flagged.map(sectionTitle).join(", ")}.
            </p>
          )}
        </div>
      )
    }
    default:
      return (
        <pre className="text-xs whitespace-pre-wrap">
          {JSON.stringify(c, null, 2)}
        </pre>
      )
  }
}

function Versions({
  jobId,
  sectionKey,
  current,
  title,
  disabled,
  onUse,
}: {
  jobId: string
  sectionKey: string
  current: number
  title: string
  disabled: boolean
  onUse: (content: Record<string, unknown>) => void
}) {
  const q = useQuery(versionsQuery(jobId, sectionKey))
  const [pick, setPick] = useState<number | null>(null)
  if (q.isPending)
    return <p className="text-sm text-muted-foreground">Loading versions...</p>
  if (q.isError)
    return (
      <p role="alert" className="text-sm text-danger">
        Couldn't load the versions. {q.error.message}
      </p>
    )
  const rows = [...q.data].sort((a, b) => b.version - a.version)
  const chosen = rows.find((r) => r.version === pick)
  return (
    <div className="grid gap-1.5 rounded-md border border-border p-2 text-sm">
      <ol
        aria-label={`Versions of ${title}`}
        className="m-0 grid list-none gap-1 p-0"
      >
        {rows.map((v) => (
          <li
            key={v.version}
            data-version={v.version}
            className="flex flex-wrap items-center gap-1.5"
          >
            <label className="inline-flex items-center gap-1.5">
              <input
                type="radio"
                name={`v-${sectionKey}`}
                checked={pick === v.version}
                disabled={v.version === current}
                onChange={() => setPick(v.version)}
              />
              Version {v.version}
            </label>
            <span className="text-faint">
              {v.origin === "owner" ? "your edit" : v.origin},{" "}
              {dateText(v.created_at)}
            </span>
            {v.version === current && <Chip tone="line">Current</Chip>}
            {v.flagged && <Chip tone="danger">Flagged</Chip>}
          </li>
        ))}
      </ol>
      {chosen && (
        <Button
          size="xs"
          className="justify-self-start"
          disabled={disabled}
          onClick={() => onUse(chosen.content)}
        >
          Use version {chosen.version} again
        </Button>
      )}
    </div>
  )
}

/** One section: its content, version history, regenerate, owner edits and the owner's note. */
export function PackSectionView({
  jobId,
  sectionKey,
  section,
  note,
  index,
  locked,
}: {
  jobId: string
  sectionKey: string
  section: PackSection
  note: string
  index: FactIndex
  /** Generation is queued or running: edits and regeneration wait. */
  locked: boolean
}) {
  const qc = useQueryClient()
  const title = sectionTitle(sectionKey)
  const notesId = useId()
  const [draftNote, setDraftNote] = useState(note)
  const [showVersions, setShowVersions] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const refresh = () => {
    void qc.invalidateQueries({
      queryKey: packKeys.versions(jobId, sectionKey),
    })
    return qc.invalidateQueries({ queryKey: packKeys.pack(jobId) })
  }
  const onError = (e: Error) => {
    const code = refusalCode(e)
    setError(
      code === "still_queued"
        ? "The pack is still being generated. Try again when it is done."
        : code === "invalid_section"
          ? `That edit doesn't fit this section: ${e.message}`
          : e.message
    )
  }
  const edit = useMutation({
    mutationFn: (content: Record<string, unknown>) =>
      editSection(jobId, sectionKey, content),
    onMutate: () => setError(null),
    onSuccess: refresh,
    onError,
  })
  const regen = useMutation({
    mutationFn: () => regenerateSection(jobId, sectionKey),
    onMutate: () => setError(null),
    onSuccess: (p) => qc.setQueryData(packKeys.pack(jobId), p),
    onError,
  })
  const saveN = useMutation({
    mutationFn: () => saveNote(jobId, sectionKey, draftNote),
    onSuccess: (p) => qc.setQueryData(packKeys.pack(jobId), p),
    onError,
  })
  const busy = edit.isPending || regen.isPending
  const problems = section.check_results.filter(
    (r) => r.status !== "pass" && !r.waived
  )

  return (
    <section
      aria-label={title}
      id={`pack-${sectionKey}`}
      data-flagged={section.flagged || undefined}
      className="grid gap-2.5"
    >
      <SectionHeader
        title={title}
        aside={`Version ${section.version}${section.origin === "owner" ? ", your edit" : ""}`}
        action={
          <span className="inline-flex items-center gap-1.5">
            <Button
              size="xs"
              variant="ghost"
              aria-expanded={showVersions}
              onClick={() => setShowVersions((s) => !s)}
            >
              <History aria-hidden="true" />
              Versions
            </Button>
            {sectionKey === "crib_sheet" && (
              <Button
                size="xs"
                variant="outline"
                onClick={() => window.print()}
              >
                <Printer aria-hidden="true" />
                Print
              </Button>
            )}
            {!CODE_SECTIONS.has(sectionKey) && (
              <Button
                size="xs"
                variant="ghost"
                disabled={busy || locked}
                onClick={() => regen.mutate()}
                aria-label={`Regenerate ${title}`}
              >
                <RefreshCw aria-hidden="true" />
                Regenerate
              </Button>
            )}
          </span>
        }
      />
      {section.flagged && (
        <div
          role="note"
          data-flag="section"
          className="grid gap-1 rounded-md border border-danger bg-danger-soft p-2 text-sm"
        >
          <span className="inline-flex items-center gap-1.5 font-semibold text-danger">
            <AlertTriangle className="size-4" aria-hidden="true" />
            Flagged: this section failed the truth checks and is left out of the
            crib sheet.
          </span>
          {problems.map((r) => (
            <span key={`${r.check}-${r.detail}`}>
              {r.check.replace(/_/g, " ")}
              {r.detail ? `: ${r.detail}` : ""}
            </span>
          ))}
        </div>
      )}
      {!section.flagged && problems.length > 0 && (
        <ul className="m-0 grid list-none gap-1 p-0 text-sm">
          {problems.map((r) => (
            <li key={`${r.check}-${r.detail}`}>
              <Chip tone={r.status === "block" ? "danger" : "warn"}>
                {r.check.replace(/_/g, " ")}
              </Chip>{" "}
              {r.detail}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      {showVersions && (
        <Versions
          jobId={jobId}
          sectionKey={sectionKey}
          current={section.version}
          title={title}
          disabled={busy || locked}
          onUse={(content) => edit.mutate(content)}
        />
      )}
      <Body
        jobId={jobId}
        sectionKey={sectionKey}
        section={section}
        index={index}
        locked={locked}
        busy={busy}
        editClaim={(path, text) =>
          edit.mutate(withClaimText(section.content, path, text))
        }
      />
      <div className="grid gap-1.5">
        <label htmlFor={notesId} className="text-sm font-semibold">
          Your notes on {title.toLowerCase()}
        </label>
        <Textarea
          id={notesId}
          rows={2}
          value={draftNote}
          onChange={(e) => setDraftNote(e.target.value)}
          placeholder="Anything you want to remember. Notes stay when you regenerate."
        />
        {draftNote !== note && (
          <Button
            size="xs"
            className="justify-self-start"
            disabled={saveN.isPending}
            onClick={() => saveN.mutate()}
          >
            Save notes
          </Button>
        )}
      </div>
    </section>
  )
}
