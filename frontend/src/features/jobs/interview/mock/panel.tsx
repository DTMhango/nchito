import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { formatCost } from "@/lib/cost"
import {
  estimateQuery,
  exportSession,
  MOCK_MODES,
  mockKeys,
  progressQuery,
  removeSession,
  roundsQuery,
  sessionsQuery,
  startSession,
  type MockMode,
  type MockSession,
} from "./api"
import { SessionView } from "./chat"

const SELECT =
  "h-9 rounded-md border border-border bg-transparent px-2 font-normal"

function Setup({
  jobId,
  onStarted,
}: {
  jobId: string
  onStarted: (id: string) => void
}) {
  const qc = useQueryClient()
  const rounds = useQuery(roundsQuery(jobId))
  const [mode, setMode] = useState<MockMode>("behavioural")
  const [length, setLength] = useState(5)
  const [usePack, setUsePack] = useState(true)
  const [each, setEach] = useState(false)
  const [timer, setTimer] = useState("")
  const [roundId, setRoundId] = useState("")
  const est = useQuery(
    estimateQuery(jobId, {
      mode,
      length,
      use_pack_questions: usePack,
      round_id: roundId || null,
    })
  )
  const start = useMutation({
    mutationFn: () =>
      startSession(jobId, {
        mode,
        length,
        use_pack_questions: usePack,
        feedback_each: each,
        timer_seconds: timer ? Number(timer) * 60 : null,
        round_id: roundId || null,
      }),
    onSuccess: (s) => {
      qc.setQueryData(mockKeys.session(s.id), s)
      void qc.invalidateQueries({ queryKey: mockKeys.list(jobId) })
      onStarted(s.id)
    },
  })
  return (
    <form
      aria-label="New mock interview"
      className="grid gap-2.5"
      onSubmit={(e) => {
        e.preventDefault()
        start.mutate()
      }}
    >
      <div className="flex flex-wrap gap-3">
        <label className="grid gap-1 text-sm font-semibold">
          Mode
          <select
            className={SELECT}
            value={mode}
            onChange={(e) => setMode(e.target.value as MockMode)}
          >
            {MOCK_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-semibold">
          Questions
          <Input
            type="number"
            min={1}
            max={30}
            value={length}
            onChange={(e) =>
              setLength(Math.max(1, Number(e.target.value) || 1))
            }
            className="w-20 font-normal"
          />
        </label>
        {(rounds.data?.length ?? 0) > 0 && (
          <label className="grid gap-1 text-sm font-semibold">
            Round
            <select
              className={SELECT}
              value={roundId}
              onChange={(e) => setRoundId(e.target.value)}
            >
              <option value="">Any round</option>
              {rounds.data!.map((r) => (
                <option key={r.id} value={r.id}>
                  Round {r.round_number}
                  {r.kind ? `: ${r.kind}` : r.format ? `: ${r.format}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="grid gap-1 text-sm font-semibold">
          Timer, minutes (optional)
          <Input
            type="number"
            min={1}
            max={60}
            value={timer}
            onChange={(e) => setTimer(e.target.value)}
            className="w-24 font-normal"
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={usePack}
          onChange={(e) => setUsePack(e.target.checked)}
        />
        Ask the pack&apos;s likely questions first
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={each}
          onChange={(e) => setEach(e.target.checked)}
        />
        Feedback after each answer (as well as at the end)
      </label>
      <p
        className="text-sm text-muted-foreground"
        data-estimate
        aria-live="polite"
      >
        {est.isSuccess
          ? `At most ${formatCost(est.data.total_micros, { currency: est.data.currency })}; it pauses and asks you past ${formatCost(est.data.budget_micros, { currency: est.data.currency })}.`
          : est.isError
            ? `No estimate: ${est.error.message}`
            : "Estimating the cost..."}
      </p>
      <Button
        type="submit"
        size="sm"
        className="justify-self-start"
        disabled={!est.isSuccess || start.isPending}
      >
        {start.isPending ? "Starting..." : "Start the interview"}
      </Button>
      {start.isError && (
        <p role="alert" className="text-sm text-danger">
          {start.error.message}
        </p>
      )}
    </form>
  )
}

function Progress({ jobId }: { jobId: string }) {
  const p = useQuery(progressQuery(jobId))
  if (!p.data || p.data.sessions === 0) return null
  return (
    <section aria-label="Progress" className="grid gap-1.5 text-sm">
      <h4 className="m-0 font-semibold">
        Progress over {p.data.sessions} session(s)
      </h4>
      <span className="flex flex-wrap gap-1">
        {p.data.categories.map((c) => (
          <Chip key={c.category} tone={c.weak ? "warn" : "good"}>
            {c.category}: {c.average} ({c.answers})
          </Chip>
        ))}
      </span>
      {p.data.practise_next.length > 0 && (
        <>
          <p className="m-0 font-semibold">Practise these next</p>
          <ul className="m-0 grid gap-0.5 pl-4">
            {p.data.practise_next.map((n) => (
              <li key={n.question}>
                {n.question}{" "}
                <span className="text-xs text-faint">
                  ({n.category}, {n.reason})
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function History({
  jobId,
  rows,
  onOpen,
}: {
  jobId: string
  rows: MockSession[]
  onOpen: (id: string) => void
}) {
  const qc = useQueryClient()
  const del = useMutation({
    mutationFn: (id: string) => removeSession(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: mockKeys.list(jobId) })
      void qc.invalidateQueries({ queryKey: mockKeys.progress(jobId) })
    },
  })
  const exp = useMutation({
    mutationFn: (id: string) => exportSession(id, "pdf"),
  })
  if (!rows.length) return null
  return (
    <section aria-label="Past sessions" className="grid gap-1.5">
      <h4 className="m-0 text-sm font-semibold">Sessions</h4>
      <ul className="m-0 grid list-none gap-1 p-0">
        {rows.map((r) => (
          <li
            key={r.id}
            data-history={r.id}
            className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2 text-sm"
          >
            <span>{new Date(r.created_at).toLocaleDateString()}</span>
            <Chip tone="line">{r.mode}</Chip>
            <Chip
              tone={
                r.status === "done"
                  ? "good"
                  : r.status === "active"
                    ? "info"
                    : "warn"
              }
            >
              {r.status}
            </Chip>
            {Object.entries(r.scores ?? {}).map(([k, v]) => (
              <span key={k} className="text-xs text-faint">
                {k} {v}
              </span>
            ))}
            <span className="ml-auto flex gap-1">
              <Button size="xs" variant="outline" onClick={() => onOpen(r.id)}>
                Open
              </Button>
              <Button
                size="xs"
                variant="ghost"
                onClick={() => exp.mutate(r.id)}
              >
                Export
              </Button>
              <Button
                size="xs"
                variant="ghost"
                disabled={del.isPending}
                onClick={() => {
                  if (window.confirm("Delete this mock interview?"))
                    del.mutate(r.id)
                }}
              >
                Delete
              </Button>
            </span>
          </li>
        ))}
      </ul>
      {(del.isError || exp.isError) && (
        <p role="alert" className="text-sm text-danger">
          {(del.error ?? exp.error)?.message}
        </p>
      )}
    </section>
  )
}

/** Mock interview in chat: set it up, practise, read the feedback, see progress. */
export function MockInterviewPanel({ jobId }: { jobId: string }) {
  const list = useQuery(sessionsQuery(jobId))
  const [open, setOpen] = useState<string | null>(null)
  const [setup, setSetup] = useState(false)
  return (
    <div
      role="region"
      aria-label="Mock interview"
      className="grid gap-4 panel p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="m-0 text-base font-semibold">Mock interview</h3>
        {open && (
          <Button size="xs" variant="ghost" onClick={() => setOpen(null)}>
            Back to sessions
          </Button>
        )}
        {!open && !setup && (
          <Button size="sm" onClick={() => setSetup(true)}>
            New mock interview
          </Button>
        )}
      </div>
      {open ? (
        <SessionView sessionId={open} jobId={jobId} />
      ) : (
        <>
          {setup && (
            <Setup
              jobId={jobId}
              onStarted={(id) => {
                setSetup(false)
                setOpen(id)
              }}
            />
          )}
          <Progress jobId={jobId} />
          <History jobId={jobId} rows={list.data ?? []} onOpen={setOpen} />
        </>
      )}
    </div>
  )
}
