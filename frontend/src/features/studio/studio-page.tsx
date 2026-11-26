import { Link } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import {
  CheckCheck,
  FileText,
  ListChecks,
  PenLine,
  Send,
  SquarePen,
} from "lucide-react"
import { ScreenEmpty } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { StagePill } from "@/components/stage-pill"
import { View } from "@/components/view"
import { pickerQuery } from "./api"
import type { StudioSearch } from "./search"
import { StudioWorkspace } from "./workspace"

/** Studio: review and edit what will be sent for one application (DESIGN 9, 10.3). */
export function StudioPage({
  search,
  onSearch,
}: {
  search: StudioSearch
  onSearch: (next: StudioSearch) => void
}) {
  return (
    <View>
      {search.application ? (
        <StudioWorkspace
          applicationId={search.application}
          runId={search.run}
          onRun={(run) => onSearch({ ...search, run })}
        />
      ) : (
        <Picker />
      )}
    </View>
  )
}

/** No application chosen: the ones in drafting or waiting for approval, newest first. */
function Picker() {
  const list = useQuery(pickerQuery())
  const apps = [...(list.data ?? [])].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at)
  )
  if (list.isPending)
    return (
      <p role="status" className="text-muted-foreground">
        Loading applications...
      </p>
    )
  if (apps.length === 0) return <Intro />
  return (
    <div className="max-w-[760px]">
      <PageHeader
        title="Choose an application"
        description="The Studio works on one application at a time: its CV, cover letter and form answers, each line traced to your Kit."
      />
      <ul className="m-0 list-none overflow-hidden rounded-lg border border-border p-0">
        {apps.map((a) => (
          <li key={a.id} className="border-t border-border first:border-t-0">
            <Link
              to="/studio"
              search={{ application: a.id }}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 row-pad hover:bg-sunken focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary-ink"
            >
              <span className="min-w-0 flex-1">
                <b className="font-semibold">{a.title}</b>
                <span className="text-muted-foreground"> · {a.employer}</span>
              </span>
              {a.next_step && (
                <span className="text-sm text-faint">{a.next_step}</span>
              )}
              <StagePill stage={a.stage} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Intro() {
  return (
    <ScreenEmpty
      icon={SquarePen}
      title="Studio"
      lead="Where one application's CV, letter and form answers are tailored, checked and sent for approval. Every line traces to an approved fact from your Kit."
      firstStep={{
        label: "Choose a role in Matches",
        to: "/matches",
        hint: "Shortlist a role, then open it here from its job page.",
      }}
      items={[
        {
          icon: ListChecks,
          title: "Requirements and keywords",
          body: "The posting's requirements, each matched Strong, Partial or Gap with its evidence, and keyword coverage.",
        },
        {
          icon: PenLine,
          title: "Structured editor",
          body: "Headline, summary, bullets and letter paragraphs you can edit and reorder, each tagged with the fact behind it.",
        },
        {
          icon: FileText,
          title: "Live A4 preview",
          body: "CV, cover letter and answers on white paper, with the template's page limits.",
        },
        {
          icon: CheckCheck,
          title: "Checks",
          body: "Fact tracing, guardrails and limits. Edits mark the checks stale until you re-check.",
        },
        {
          icon: Send,
          title: "Send for approval",
          body: "When nothing blocks it, the packet goes to the approval receipt.",
        },
      ]}
    />
  )
}
