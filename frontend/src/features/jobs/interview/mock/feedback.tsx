import { AlertTriangle } from "lucide-react"
import { Chip } from "@/components/chip"
import type {
  AnswerFeedback,
  FinalFeedback,
  KeptClaim,
  RemovedClaim,
} from "./api"

/** What a suggested sentence rests on: Kit facts, or the owner's own words in this session. */
function Sources({ claim }: { claim: KeptClaim }) {
  return (
    <span className="inline-flex flex-wrap gap-1" data-sources>
      {claim.sources.map((s) =>
        s.kind === "fact" ? (
          <Chip key={s.code} tone="primary" title={s.text} data-fact={s.code}>
            {s.code}
          </Chip>
        ) : (
          <Chip
            key={s.code}
            tone="accent"
            title={s.text}
            data-your-words={s.code}
          >
            Your words {s.code}
          </Chip>
        )
      )}
    </span>
  )
}

function Removed({ items }: { items: RemovedClaim[] }) {
  if (!items.length) return null
  return (
    <div className="grid gap-1" data-removed>
      <p className="text-xs font-semibold text-warn">
        Removed from the suggestion: failed the truth checks
      </p>
      <ul className="m-0 grid list-none gap-1 p-0">
        {items.map((r, i) => (
          <li
            key={i}
            data-flagged-claim
            className="flex items-start gap-1.5 rounded-md bg-warn-soft p-2 text-sm text-warn"
          >
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0"
              aria-hidden="true"
            />
            <span className="grid gap-0.5">
              <span className="line-through decoration-1">
                {r.text ??
                  "(withheld: it used material you keep out of AI prompts)"}
              </span>
              <span className="text-xs">{r.reasons.join("; ")}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Scores({ scores }: { scores: Record<string, number> }) {
  const entries = Object.entries(scores)
  if (!entries.length) return null
  return (
    <span className="flex flex-wrap gap-1" aria-label="Scores">
      {entries.map(([k, v]) => (
        <Chip key={k} tone="neutral">
          {k}: {v}
        </Chip>
      ))}
    </span>
  )
}

/** Checked feedback on one answer. */
export function AnswerFeedbackView({ fb }: { fb: AnswerFeedback }) {
  return (
    <div className="grid gap-2 text-sm">
      <Scores scores={fb.scores} />
      {fb.withheld && <p className="text-xs text-warn">{fb.withheld}</p>}
      {(
        [
          ["Structure", fb.structure],
          ["Relevance", fb.relevance],
          ["Specificity", fb.specificity],
        ] as const
      )
        .filter(([, t]) => t)
        .map(([label, t]) => (
          <p key={label}>
            <span className="font-semibold">{label}: </span>
            {t}
          </p>
        ))}
      {fb.strong.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {fb.strong.map((s) => (
            <Chip key={s} tone="good">
              {s}
            </Chip>
          ))}
        </span>
      )}
      {fb.tighten.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {fb.tighten.map((s) => (
            <Chip key={s} tone="warn">
              Tighten: {s}
            </Chip>
          ))}
        </span>
      )}
      {fb.suggested.length > 0 && (
        <div className="grid gap-1">
          <p className="text-xs font-semibold text-muted-foreground">
            A stronger answer, from your facts and your own words
          </p>
          <ul className="m-0 grid list-none gap-1 p-0">
            {fb.suggested.map((c, i) => (
              <li key={i} data-suggested className="grid gap-0.5">
                <span>{c.text}</span>
                <Sources claim={c} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <Removed items={fb.removed} />
    </div>
  )
}

/** The end-of-session feedback. */
export function FinalFeedbackView({ fb }: { fb: FinalFeedback }) {
  return (
    <section aria-label="Feedback" className="grid gap-3">
      <h4 className="m-0 text-base font-semibold">Feedback</h4>
      {fb.summary && <p className="text-sm">{fb.summary}</p>}
      <Scores scores={fb.overall} />
      {fb.answers.length === 0 && (
        <p className="text-sm text-muted-foreground">No answers to review.</p>
      )}
      {fb.answers.map((a) => (
        <article
          key={a.question_index}
          className="grid gap-1.5 rounded-md border border-border bg-surface p-3"
        >
          <p className="m-0 font-semibold">
            {a.question || `Question ${a.question_index + 1}`}
          </p>
          <AnswerFeedbackView fb={a} />
        </article>
      ))}
    </section>
  )
}
