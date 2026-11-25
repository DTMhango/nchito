import {
  Activity,
  BriefcaseBusiness,
  FileText,
  Gauge,
  Mail,
  MessagesSquare,
  NotebookText,
  ScrollText,
  Send,
  Users,
  type LucideIcon,
} from "lucide-react"
import { Link } from "@tanstack/react-router"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SubNav, SubNavLink } from "@/components/sub-nav"
import { View } from "@/components/view"
import { WhyPanel } from "@/components/why-panel"

export const JOB_TABS = [
  "overview",
  "posting",
  "fit",
  "documents",
  "application",
  "messages",
  "people",
  "interview",
  "activity",
] as const
export type JobTab = (typeof JOB_TABS)[number]

const TAB_META: Record<
  JobTab,
  { label: string; icon: LucideIcon; title: string; body: string }
> = {
  overview: {
    label: "Overview",
    icon: BriefcaseBusiness,
    title: "Key facts and why it fits",
    body: "Facets with the sentence behind each, pay, location and visa picture, why it fits, gaps, whether it won or is held in its employer group, tags and your notes.",
  },
  posting: {
    label: "Posting",
    icon: ScrollText,
    title: "The posting as captured",
    body: "The text exactly as read, every sighting and link, change history if it was reposted or edited, and whether it is still open.",
  },
  fit: {
    label: "Fit",
    icon: Gauge,
    title: "Score breakdown",
    body: "Each criterion with its weight, rating and the facts cited as evidence, filter results, the requirement table, rubric version and any overrides.",
  },
  documents: {
    label: "Documents",
    icon: FileText,
    title: "CV, letter and attachments",
    body: "Drafts open in the Studio. After applying, this shows the exact files that were sent, read-only.",
  },
  application: {
    label: "Application",
    icon: Send,
    title: "How it was applied",
    body: "Channel, the answers given on the form, confirmation evidence, agent steps and checkpoints, open pending actions, and what a runner was given.",
  },
  messages: {
    label: "Messages",
    icon: Mail,
    title: "Email about this role",
    body: "Threads linked to this role with their classification (confirmation, rejection, interview). Draft a reply or a follow-up from here.",
  },
  people: {
    label: "People",
    icon: Users,
    title: "Recruiter, hiring manager, interviewers",
    body: "Name, role, link and notes for each person, added by you or picked up from emails.",
  },
  interview: {
    label: "Interview",
    icon: MessagesSquare,
    title: "Interview pack",
    body: "Role and company briefs, likely questions with answers built from your facts, your gaps, what you told them, pay position and one entry per round.",
  },
  activity: {
    label: "Activity",
    icon: Activity,
    title: "Timeline and audit trail",
    body: "Every stage change, edit, approval, agent step and email for this role, with who did it.",
  },
}

/** One page per role (DESIGN 10.3a), at a stable link. Tabs are shells in wave 0. */
export function JobPage({ id, tab }: { id: string; tab: JobTab }) {
  const meta = TAB_META[tab]
  return (
    <View>
      <header className="grid gap-2 border-b border-border pb-4.5">
        <span className="eyebrow">
          Role <span className="num">{id}</span>
        </span>
        <div className="flex flex-wrap items-center gap-3">
          <Skeleton
            className="h-7 w-[min(360px,70vw)] bg-sunken"
            aria-hidden="true"
          />
          <Chip tone="line">Not loaded</Chip>
        </div>
        <p className="max-w-[70ch] text-muted-foreground">
          This role isn't in your list yet. Once roles arrive from a sweep or
          Add job, this header shows the role, employer, stage, score, deadline,
          the next step and the actions you can take right now.
        </p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          <Button asChild size="sm" variant="outline">
            <Link to="/matches">Back to Matches</Link>
          </Button>
        </div>
      </header>

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

      <div className="grid items-start gap-7 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section
          aria-label={meta.label}
          className="rounded-lg border border-dashed border-border-strong"
        >
          <EmptyState
            icon={meta.icon}
            title={meta.title}
            description={meta.body}
          />
        </section>
        {tab === "overview" ? (
          <WhyPanel reasons={[]} />
        ) : (
          <aside className="flex items-start gap-3 rounded-lg bg-sunken p-4 text-sm text-muted-foreground">
            <NotebookText
              className="mt-0.5 size-4 shrink-0"
              aria-hidden="true"
            />
            Everything about a role lives on this page. Matches, Applications,
            Today, search and notifications all link here.
          </aside>
        )}
      </div>
    </View>
  )
}
