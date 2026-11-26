import {
  Activity,
  BriefcaseBusiness,
  ExternalLink,
  FileText,
  Columns3,
  Gauge,
  History,
  Mail,
  MessagesSquare,
  Pin,
  PinOff,
  ScrollText,
  Send,
  Users,
  type LucideIcon,
} from "lucide-react"
import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { ScoreRing } from "@/components/score-ring"
import { StagePill } from "@/components/stage-pill"
import { SubNav, SubNavLink } from "@/components/sub-nav"
import { View } from "@/components/view"
import { recheckSummary } from "./recheck"
import {
  applicationQuery,
  jobKeys,
  jobQuery,
  patchJob,
  recheckJob,
  type JobDetail,
} from "./api"
import { deadlineText } from "./format"
import { CorrectionsMenu } from "./corrections/corrections-menu"
import { WhyButton } from "./why-sheet"
import { ActivityTab } from "./tabs/activity-tab"
import { ApplicationTab } from "./tabs/application-tab"
import { ComingTab } from "./tabs/coming-tab"
import { ChangesTab, StalePacketBanner } from "./changes/changes-tab"
import { InterviewTab } from "./interview/interview-tab"
import { InterviewOffer } from "./interview/offer-banner"
import { FitTab } from "./tabs/fit-tab"
import { MessagesTab } from "./tabs/messages-tab"
import { OverviewTab } from "./tabs/overview-tab"
import { PeopleTab } from "./tabs/people-tab"
import { PostingTab } from "./tabs/posting-tab"

import { JOB_TABS, type JobTab } from "./job-tabs"

export { JOB_TABS, type JobTab }

const TAB_META: Record<JobTab, { label: string; icon: LucideIcon }> = {
  overview: { label: "Overview", icon: BriefcaseBusiness },
  posting: { label: "Posting", icon: ScrollText },
  fit: { label: "Fit", icon: Gauge },
  documents: { label: "Documents", icon: FileText },
  application: { label: "Application", icon: Send },
  messages: { label: "Messages", icon: Mail },
  people: { label: "People", icon: Users },
  interview: { label: "Interview", icon: MessagesSquare },
  changes: { label: "Changes", icon: History },
  activity: { label: "Activity", icon: Activity },
}

const TRIAGE_LABEL: Record<JobDetail["triage"], string> = {
  new: "New",
  shortlisted: "Shortlisted",
  below_threshold: "Below threshold",
  archived: "Archived",
  skipped: "Skipped",
}

/** One page per role (DESIGN 10.3a), at a stable link. The tab lives in the URL. */
export function JobPage({ id, tab }: { id: string; tab: JobTab }) {
  const job = useQuery(jobQuery(id))

  if (job.isPending)
    return (
      <View>
        <Skeleton
          className="h-8 w-[min(360px,70vw)] bg-sunken"
          aria-label="Loading the role"
        />
      </View>
    )
  if (job.isError || !job.data)
    return (
      <View>
        <EmptyState
          title="This role isn't in your list"
          description="It may have been merged into another role or removed. Matches lists everything that is."
          actions={
            <Button asChild size="sm" variant="outline">
              <Link to="/matches">Back to Matches</Link>
            </Button>
          }
        />
      </View>
    )

  return (
    <View>
      <JobHeader job={job.data} />
      <StalePacketBanner jobId={job.data.id} />
      {tab !== "interview" && <InterviewOffer job={job.data} />}
      <SubNav label="Role sections" className="mt-1 mb-5">
        {JOB_TABS.map((t) => {
          const Icon = TAB_META[t].icon
          return (
            <SubNavLink
              key={t}
              to="/jobs/$id"
              params={{ id }}
              search={{ tab: t }}
              activeOptions={{ includeSearch: true }}
            >
              <Icon
                className="size-[15px]"
                strokeWidth={1.5}
                aria-hidden="true"
              />
              {TAB_META[t].label}
            </SubNavLink>
          )
        })}
      </SubNav>
      <section aria-label={TAB_META[tab].label} className="min-w-0">
        {tab === "overview" && <OverviewTab job={job.data} />}
        {tab === "posting" && <PostingTab job={job.data} />}
        {tab === "fit" && <FitTab job={job.data} />}
        {tab === "documents" && (
          <ComingTab tab="documents" applicationId={job.data.application_id} />
        )}
        {tab === "application" && <ApplicationTab job={job.data} />}
        {tab === "messages" && <MessagesTab job={job.data} />}
        {tab === "people" && <PeopleTab job={job.data} />}
        {tab === "interview" && <InterviewTab job={job.data} />}
        {tab === "changes" && <ChangesTab job={job.data} />}
        {tab === "activity" && <ActivityTab job={job.data} />}
      </section>
    </View>
  )
}

function JobHeader({ job }: { job: JobDetail }) {
  const qc = useQueryClient()
  const app = useQuery(applicationQuery(job.application_id))
  const patch = useMutation({
    mutationFn: (body: Parameters<typeof patchJob>[1]) =>
      patchJob(job.id, body),
    onSuccess: (next) => {
      qc.setQueryData(jobKeys.job(job.id), next)
      void qc.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
  const recheck = useMutation({
    mutationFn: () => recheckJob(job.id),
    onSuccess: (r) => {
      qc.setQueryData(jobKeys.job(job.id), r.job)
      toast.success(recheckSummary(r))
    },
  })
  const application = app.data
  const applyUrl = job.apply_url ?? job.sightings[0]?.url

  return (
    <header className="grid gap-3 border-b border-border pb-4.5">
      <div className="flex flex-wrap items-start gap-4">
        {job.best_score != null && (
          <ScoreRing score={job.best_score} size={64} />
        )}
        <div className="grid min-w-0 flex-1 basis-72 gap-1.5">
          <span className="eyebrow">{job.canonical_employer}</span>
          <h2 className="text-2xl">{job.title}</h2>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted-foreground">
            {application ? (
              <StagePill stage={application.stage} />
            ) : (
              <Chip tone="line">{TRIAGE_LABEL[job.triage]}</Chip>
            )}
            {job.conflict_state === "held" && <Chip tone="warn">Held</Chip>}
            <span>
              Deadline:{" "}
              <b className="text-foreground">{deadlineText(job.deadline)}</b>
            </span>
            <span>
              Next step:{" "}
              <b className="text-foreground">
                {application?.next_step ??
                  (job.triage === "new"
                    ? "Decide whether to shortlist it"
                    : "None yet")}
              </b>
            </span>
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center gap-1.5 sm:w-auto">
          <WhyButton jobId={job.id} />
          <Button asChild size="sm" variant="outline">
            <Link to="/compare" search={{ ids: job.id }}>
              <Columns3 aria-hidden="true" />
              Compare
            </Link>
          </Button>
          <CorrectionsMenu job={job} />
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5" aria-label="Actions">
        {(job.triage === "new" || job.triage === "below_threshold") && (
          <Button
            size="sm"
            onClick={() => patch.mutate({ triage: "shortlisted" })}
          >
            Shortlist
          </Button>
        )}
        {job.triage !== "skipped" && !application && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => patch.mutate({ triage: "skipped" })}
          >
            Skip
          </Button>
        )}
        {application && (
          <Button asChild size="sm" variant="outline">
            <Link to="/studio" search={{ application: application.id }}>
              Open in Studio
            </Link>
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => patch.mutate({ pinned: !job.pinned })}
        >
          {job.pinned ? (
            <PinOff aria-hidden="true" />
          ) : (
            <Pin aria-hidden="true" />
          )}
          {job.pinned ? "Unpin" : "Pin"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={recheck.isPending}
          onClick={() => recheck.mutate()}
        >
          Check the posting again
        </Button>
        {applyUrl && (
          <Button asChild size="sm" variant="ghost">
            <a href={applyUrl} target="_blank" rel="noreferrer noopener">
              <ExternalLink aria-hidden="true" />
              Open the posting
            </a>
          </Button>
        )}
      </div>
    </header>
  )
}
