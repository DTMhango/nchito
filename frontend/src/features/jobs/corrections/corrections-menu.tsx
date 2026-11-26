import { useState } from "react"
import { Building2, CheckCheck, GitMerge, Split, Wrench } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { JobDetail } from "../api"
import { AppliedMyselfDialog } from "./applied-myself-dialog"
import { EmployerDialog } from "./employer-dialog"
import { MergeDialog } from "./merge-dialog"
import { SplitDialog } from "./split-dialog"

type Which = "applied" | "merge" | "split" | "employer" | null

/** The Corrections menu (DESIGN 18.4): four ways to fix what the system got wrong. */
export function CorrectionsMenu({ job }: { job: JobDetail }) {
  const [which, setWhich] = useState<Which>(null)
  const close = (v: boolean) => {
    if (!v) setWhich(null)
  }
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <Wrench aria-hidden="true" />
            Corrections
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setWhich("applied")}>
            <CheckCheck aria-hidden="true" /> I applied myself
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setWhich("merge")}>
            <GitMerge aria-hidden="true" /> Merge with another job
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setWhich("split")}>
            <Split aria-hidden="true" /> Split a wrong merge
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setWhich("employer")}>
            <Building2 aria-hidden="true" /> Wrong employer
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {which === "applied" && (
        <AppliedMyselfDialog jobId={job.id} open onOpenChange={close} />
      )}
      {which === "merge" && <MergeDialog job={job} open onOpenChange={close} />}
      {which === "split" && <SplitDialog job={job} open onOpenChange={close} />}
      {which === "employer" && (
        <EmployerDialog job={job} open onOpenChange={close} />
      )}
    </>
  )
}
