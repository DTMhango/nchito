import { Link } from "@tanstack/react-router"
import {
  BookOpen,
  CircleHelp,
  Lock,
  ShieldCheck,
  UserRound,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { cn } from "@/lib/utils"
import { needsOwner, type ScreeningRow } from "./draft"

const CLASS_LABEL = {
  auto: "Reused freely",
  ask_first: "Ask first",
  never: "Never answered",
  owner_only: "Only you",
} as const

/**
 * The form's screening questions, each with its source in the answer bank. Unknown is not
 * yes: a question without a confirmed answer shows no value at all, only that it needs you.
 */
export function AnswersPanel({
  rows,
  loading,
}: {
  rows: ScreeningRow[]
  loading: boolean
}) {
  if (loading)
    return <p className="text-sm text-muted-foreground">Loading the form...</p>
  if (rows.length === 0)
    return (
      <div className="grid gap-1 rounded-md bg-sunken p-4 text-sm">
        <b>No form questions yet</b>
        <span className="text-muted-foreground">
          Questions appear here once the application form has been read. Each
          one is answered from your answer bank, or asks you first.
        </span>
      </div>
    )
  const open = rows.filter(needsOwner)
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        {open.length === 0
          ? "Every question has a confirmed answer."
          : `${open.length} of ${rows.length} question${rows.length === 1 ? "" : "s"} need${open.length === 1 ? "s" : ""} you before this can be sent.`}
      </p>
      <ul
        className="m-0 grid list-none gap-2 p-0"
        aria-label="Screening answers"
      >
        {rows.map((r) => (
          <AnswerRow key={r.question} row={r} />
        ))}
      </ul>
    </div>
  )
}

function AnswerRow({ row }: { row: ScreeningRow }) {
  const s = row.standing
  const owner = needsOwner(row)
  const answer = "answer" in s ? s.answer : null
  return (
    <li
      role="group"
      aria-label={row.question}
      data-standing={s.kind}
      className={cn(
        "grid gap-1.5 rounded-md border border-border bg-surface p-3",
        owner && "border-l-4 border-l-info"
      )}
    >
      <div className="flex flex-wrap items-start gap-2">
        <b className="min-w-0 flex-1 font-semibold">{row.question}</b>
        {row.material && <Chip tone="warn">Material</Chip>}
      </div>

      {s.kind === "confirmed" && (
        <div className="flex flex-wrap items-center gap-2">
          <ShieldCheck aria-hidden="true" className="size-4 text-good" />
          <span className="font-medium">{s.value}</span>
        </div>
      )}
      {s.kind === "declined" && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Lock aria-hidden="true" className="size-4 text-faint" />
          {s.select
            ? `Picks "${s.select}" where an answer is forced`
            : "Left unanswered, by your rule"}
        </div>
      )}
      {owner && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {s.kind === "owner_only" ? (
            <UserRound aria-hidden="true" className="size-4 text-info" />
          ) : (
            <CircleHelp aria-hidden="true" className="size-4 text-info" />
          )}
          <span className="font-medium text-info">
            {s.kind === "unknown"
              ? "Needs your answer"
              : s.kind === "owner_only"
                ? "Only you can answer this"
                : "Needs your confirmation"}
          </span>
          <span className="text-muted-foreground">
            {s.kind === "unknown"
              ? "Not in your answer bank. Nothing is filled in until you answer."
              : s.kind === "unconfirmed"
                ? `${s.reason}. Nothing is filled in until you confirm.`
                : "Nothing is filled in for you."}
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
        {answer ? (
          <span className="inline-flex items-center gap-1">
            <BookOpen aria-hidden="true" className="size-3.5" />
            Answer bank: “{answer.patterns.canonical}” ·{" "}
            {CLASS_LABEL[answer.answer_class ?? "ask_first"]}
            {answer.confirmed_at && (
              <> · confirmed {answer.confirmed_at.slice(0, 10)}</>
            )}
          </span>
        ) : (
          <span>No answer bank entry</span>
        )}
        {owner && (
          <span className="ml-auto flex gap-1.5">
            {row.action && (
              <Button asChild size="xs" variant="outline">
                <Link to="/today">Answer on Today</Link>
              </Button>
            )}
            <Button asChild size="xs" variant="ghost">
              <Link to="/kit/answers">Open the answer bank</Link>
            </Button>
          </span>
        )}
      </div>
    </li>
  )
}
