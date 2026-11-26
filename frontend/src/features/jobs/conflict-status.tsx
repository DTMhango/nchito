import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Crown, PauseCircle, UnlockKeyhole } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { searchJobsQuery, type JobDetail } from "./api"
import { ReleaseDialog } from "./corrections/release-dialog"

/** Wording for a held role: "held: outranked by <role>, 88 vs 74". Pure, so it is tested alone. */
export function heldSentence(
  winnerTitle: string | null,
  winnerScore: number | null | undefined,
  ownScore: number | null | undefined,
  note: string | null
) {
  if (!winnerTitle)
    return note ?? "held: another role at this employer outranks it"
  const scores =
    winnerScore != null && ownScore != null
      ? `, ${winnerScore} vs ${ownScore}`
      : ""
  return `held: outranked by ${winnerTitle}${scores}`
}

/** One role per employer (DESIGN 7.1): winner, held (with a way out) or released. */
export function ConflictStatus({ job }: { job: JobDetail }) {
  const [releasing, setReleasing] = useState(false)
  const held = job.conflict_state === "held"
  const peers = useQuery(searchJobsQuery(job.canonical_employer, held))
  const winner = peers.data?.find(
    (j) =>
      j.id !== job.id &&
      j.canonical_employer === job.canonical_employer &&
      j.conflict_state === "winner"
  )

  if (job.conflict_state === "none")
    return (
      <p className="text-sm text-muted-foreground">
        No other role at {job.canonical_employer} competes with this one.
      </p>
    )
  if (job.conflict_state === "winner")
    return (
      <p className="flex flex-wrap items-center gap-2">
        <Chip tone="good" icon={Crown}>
          Winner
        </Chip>
        <span className="text-sm">
          The highest-scoring role at {job.canonical_employer}.
          {job.conflict_note ? ` ${job.conflict_note}` : ""}
        </span>
      </p>
    )
  if (job.conflict_state === "released")
    return (
      <p className="flex flex-wrap items-center gap-2">
        <Chip tone="info" icon={UnlockKeyhole}>
          Released
        </Chip>
        <span className="text-sm">
          You released this role even though another one outranks it.
          {job.conflict_note ? ` ${job.conflict_note}` : ""}
        </span>
      </p>
    )
  return (
    <div className="grid gap-2">
      <p className="flex flex-wrap items-center gap-2">
        <Chip tone="warn" icon={PauseCircle}>
          Held
        </Chip>
        <span className="text-sm" data-testid="held-sentence">
          {heldSentence(
            winner?.title ?? null,
            winner?.best_score,
            job.best_score,
            job.conflict_note ?? null
          )}
        </span>
      </p>
      {winner && (
        <Link
          to="/jobs/$id"
          params={{ id: winner.id }}
          search={{ tab: "overview" }}
          className="w-fit text-sm text-primary-ink underline"
        >
          Open {winner.title}
        </Link>
      )}
      <div>
        <Button size="sm" variant="outline" onClick={() => setReleasing(true)}>
          Release this role
        </Button>
      </div>
      <ReleaseDialog
        jobId={job.id}
        title={job.title}
        open={releasing}
        onOpenChange={setReleasing}
      />
    </div>
  )
}
