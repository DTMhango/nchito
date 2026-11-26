import { Link } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { GraduationCap } from "lucide-react"
import { Button } from "@/components/ui/button"
import { applicationQuery, type JobDetail } from "../api"
import { packQuery } from "./api"

/** At the interview stage with no pack yet, offer one (DESIGN 10.3a). */
export function InterviewOffer({ job }: { job: JobDetail }) {
  const app = useQuery(applicationQuery(job.application_id))
  const atInterview = app.data?.stage === "interview"
  const pack = useQuery({
    ...packQuery(job.application_id),
    enabled: atInterview,
  })
  if (!atInterview || pack.data !== null) return null
  return (
    <div
      role="status"
      data-banner="interview-offer"
      className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-highlight-soft px-3 py-2 text-sm text-highlight-ink"
    >
      <GraduationCap className="size-4" aria-hidden="true" />
      <span className="font-semibold">
        You have an interview. Prepare with a pack built from your facts.
      </span>
      <Button asChild size="xs" className="ml-auto">
        <Link
          to="/jobs/$id"
          params={{ id: job.id }}
          search={{ tab: "interview" }}
        >
          Build the pack
        </Link>
      </Button>
    </div>
  )
}
