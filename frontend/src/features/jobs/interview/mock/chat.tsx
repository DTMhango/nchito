import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { PauseCircle, RotateCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { formatCost } from "@/lib/cost"
import { packKeys } from "../api"
import {
  answer,
  finish,
  mockKeys,
  resolveClaim,
  resume,
  saveStory,
  sessionQuery,
  type AnswerFeedback,
  type FinalFeedback,
  type MockSession,
  type MockTurn,
} from "./api"
import { AnswerFeedbackView, FinalFeedbackView } from "./feedback"

/** A calm countdown for the open question (display only; remounted per question by its key). */
function Timer({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(t)
  }, [])
  const m = Math.floor(left / 60)
  const s = String(left % 60).padStart(2, "0")
  return (
    <span
      role="timer"
      aria-label="Time left for this answer"
      className={left === 0 ? "text-xs text-warn" : "text-xs text-faint"}
    >
      {m}:{s}
    </span>
  )
}

function Claims({ session, turn }: { session: MockSession; turn: MockTurn }) {
  const qc = useQueryClient()
  const act = useMutation({
    mutationFn: (v: { id: string; action: "add_draft" | "dismiss" }) =>
      resolveClaim(session.id, turn.id, v.id, v.action),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: mockKeys.session(session.id) }),
  })
  const claims = turn.claims ?? []
  if (!claims.length) return null
  return (
    <ul className="m-0 grid list-none gap-1 p-0" aria-label="Not in your Kit">
      {claims.map((c) => (
        <li
          key={c.id}
          data-claim={c.id}
          data-status={c.status}
          className="grid gap-1 rounded-md bg-info-soft p-2 text-sm"
        >
          <span>&ldquo;{c.text}&rdquo;</span>
          {c.status === "unverified" ? (
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-info">
                {session.unverified_prompt}
              </span>
              <Button
                size="xs"
                variant="outline"
                disabled={act.isPending}
                onClick={() => act.mutate({ id: c.id, action: "add_draft" })}
              >
                Add as draft fact
              </Button>
              <Button
                size="xs"
                variant="ghost"
                disabled={act.isPending}
                onClick={() => act.mutate({ id: c.id, action: "dismiss" })}
              >
                Dismiss
              </Button>
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">
              {c.status === "added"
                ? `Added to your library as draft ${c.fact_code ?? ""} (review it there)`
                : "Dismissed"}
            </span>
          )}
        </li>
      ))}
      {act.isError && (
        <li role="alert" className="text-sm text-danger">
          {act.error.message}
        </li>
      )}
    </ul>
  )
}

function SaveStory({
  jobId,
  session,
  turn,
}: {
  jobId: string
  session: MockSession
  turn: MockTurn
}) {
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () => saveStory(session.id, turn.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: packKeys.pack(jobId) }),
  })
  if (save.isSuccess)
    return (
      <Chip tone={save.data.flagged ? "warn" : "good"}>
        {save.data.flagged
          ? "Saved to the story bank, flagged by the truth checks"
          : "Saved to the story bank"}
      </Chip>
    )
  return (
    <span className="flex items-center gap-1.5">
      <Button
        size="xs"
        variant="outline"
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        Save to story bank
      </Button>
      {save.isError && (
        <span role="alert" className="text-xs text-danger">
          {save.error.message}
        </span>
      )}
    </span>
  )
}

function Turn({
  jobId,
  session,
  turn,
}: {
  jobId: string
  session: MockSession
  turn: MockTurn
}) {
  if (turn.role === "coach")
    return (
      <li
        data-turn={turn.step_key}
        className="rounded-md border border-border bg-sunken p-3"
      >
        <p className="m-0 mb-1 text-xs font-semibold text-muted-foreground">
          Feedback
        </p>
        {turn.feedback && (
          <AnswerFeedbackView fb={turn.feedback as unknown as AnswerFeedback} />
        )}
      </li>
    )
  const mine = turn.role === "owner"
  return (
    <li
      data-turn={turn.step_key}
      className={
        mine ? "grid justify-items-end gap-1" : "grid justify-items-start gap-1"
      }
    >
      <span className="text-xs text-faint">
        {mine
          ? "You"
          : turn.kind === "probe"
            ? "Interviewer (follow-up)"
            : "Interviewer"}
        {turn.category && !mine ? ` · ${turn.category}` : ""}
      </span>
      <p
        className={
          mine
            ? "m-0 max-w-[85%] rounded-md bg-primary-soft p-2.5 text-sm whitespace-pre-wrap"
            : "m-0 max-w-[85%] rounded-md bg-surface p-2.5 text-sm whitespace-pre-wrap"
        }
      >
        {turn.kind === "skip" ? <em>Skipped</em> : turn.text}
      </p>
      {mine && <Claims session={session} turn={turn} />}
      {mine && turn.kind === "answer" && session.status === "done" && (
        <SaveStory jobId={jobId} session={session} turn={turn} />
      )}
    </li>
  )
}

function Paused({ jobId, session }: { jobId: string; session: MockSession }) {
  const qc = useQueryClient()
  const [raise, setRaise] = useState("")
  const again = useMutation({
    mutationFn: () =>
      resume(session.id, raise ? Math.round(Number(raise) * 1_000_000) : null),
    onSuccess: (s) => {
      qc.setQueryData(mockKeys.session(session.id), s)
      return qc.invalidateQueries({ queryKey: mockKeys.list(jobId) })
    },
  })
  const paused = session.status === "paused"
  return (
    <div
      role="alert"
      data-paused
      className="grid gap-2 rounded-md bg-warn-soft p-3 text-sm"
    >
      <span className="inline-flex items-center gap-1.5 font-semibold text-warn">
        <PauseCircle className="size-4" aria-hidden="true" />
        {paused
          ? "Paused: the AI budget for this session is used up"
          : "Something went wrong"}
      </span>
      {session.error && <span className="text-xs">{session.error}</span>}
      <span className="text-xs">
        Spent {formatCost(session.cost_micros)}
        {session.budget_micros != null &&
          ` of ${formatCost(session.budget_micros)}`}
        . Your answers are saved; resuming picks up where it stopped.
      </span>
      {paused && (
        <label className="grid max-w-60 gap-1 text-xs font-semibold">
          Raise the session budget to (optional)
          <Input
            type="number"
            min={0}
            step="0.01"
            value={raise}
            onChange={(e) => setRaise(e.target.value)}
          />
        </label>
      )}
      <Button
        size="sm"
        variant="outline"
        className="justify-self-start"
        disabled={again.isPending}
        onClick={() => again.mutate()}
      >
        <RotateCw aria-hidden="true" />
        {paused ? "Resume" : "Try again"}
      </Button>
      {again.isError && (
        <span className="text-danger">{again.error.message}</span>
      )}
    </div>
  )
}

/** One mock interview: the chat, the composer, the paused state and the feedback. */
export function SessionView({
  sessionId,
  jobId,
}: {
  sessionId: string
  jobId: string
}) {
  const qc = useQueryClient()
  const q = useQuery(sessionQuery(sessionId))
  const [text, setText] = useState("")
  const box = useRef<HTMLTextAreaElement>(null)
  const settle = (s: MockSession) => {
    qc.setQueryData(mockKeys.session(sessionId), s)
    void qc.invalidateQueries({ queryKey: mockKeys.list(jobId) })
    void qc.invalidateQueries({ queryKey: mockKeys.progress(jobId) })
  }
  const send = useMutation({
    mutationFn: (skip: boolean) =>
      answer(sessionId, {
        text: skip ? "" : text,
        skip,
        turn_key: q.data?.expects ?? null,
      }),
    onSuccess: (s) => {
      setText("")
      settle(s)
    },
  })
  const done = useMutation({
    mutationFn: () => finish(sessionId),
    onSuccess: settle,
  })
  const s = q.data
  const waiting = !!s?.expects
  useEffect(() => {
    if (waiting) box.current?.focus()
  }, [waiting, s?.turns.length])

  if (q.isPending)
    return (
      <p className="text-sm text-muted-foreground">Loading the interview...</p>
    )
  if (q.isError)
    return (
      <p role="alert" className="text-sm text-danger">
        {q.error.message}
      </p>
    )
  const session = q.data
  const busy = send.isPending || done.isPending
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim() && !busy) {
      e.preventDefault()
      send.mutate(false)
    }
  }
  return (
    <div
      className="grid gap-3"
      data-session={session.id}
      data-status={session.status}
    >
      <ol
        aria-label="Interview"
        aria-live="polite"
        className="m-0 grid list-none gap-2.5 p-0"
      >
        {session.turns.map((t) => (
          <Turn key={t.id} jobId={jobId} session={session} turn={t} />
        ))}
      </ol>
      {busy && (
        <p role="status" className="text-sm text-muted-foreground">
          {done.isPending
            ? "Reviewing your answers..."
            : "The interviewer is thinking..."}
        </p>
      )}
      {(session.status === "paused" || session.status === "failed") && (
        <Paused jobId={jobId} session={session} />
      )}
      {waiting && (
        <div className="grid gap-2">
          <label className="grid gap-1 text-sm font-semibold">
            <span className="flex items-center justify-between">
              Your answer
              {session.timer_seconds ? (
                <Timer
                  key={session.expects ?? ""}
                  seconds={session.timer_seconds}
                />
              ) : null}
            </span>
            <Textarea
              ref={box}
              rows={6}
              value={text}
              disabled={busy}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKey}
              className="font-normal"
              placeholder="Answer as you would in the room. Ctrl+Enter to send."
            />
          </label>
          <span className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              disabled={!text.trim() || busy}
              onClick={() => send.mutate(false)}
            >
              Send
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => send.mutate(true)}
            >
              Skip question
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => done.mutate()}
            >
              I&apos;m done
            </Button>
          </span>
        </div>
      )}
      {(send.isError || done.isError) && (
        <p role="alert" className="text-sm text-danger">
          {(send.error ?? done.error)?.message}
        </p>
      )}
      {session.status === "done" && session.feedback && (
        <FinalFeedbackView fb={session.feedback as unknown as FinalFeedback} />
      )}
      {session.cost_micros > 0 && (
        <span className="text-xs text-faint">
          Cost {formatCost(session.cost_micros)}
        </span>
      )}
    </div>
  )
}
