import { useMemo, useState } from "react"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/page-header"
import { Segmented } from "@/components/segmented"
import {
  useKitList,
  type ExperienceOut,
  type FactOut,
  type TrackOut,
} from "./api"
import {
  ListEmpty,
  NativeSelect,
  QueryGate,
  ReviewBanner,
  SearchBox,
  useReviewFor,
} from "./common"
import { ExperienceCard, ExperienceDialog } from "./experience"
import { FactDialog, FactRow } from "./fact-row"
import { FACT_STATUS } from "./labels"
import { ReferencesTab, SkillsTab } from "./skills-refs"

type Tab = "experience" | "skills" | "education" | "references"

type FactDialogState = {
  fact: FactOut | null
  experienceId?: string | null
  kind?: FactOut["kind"]
} | null

/** Kit, Library (DESIGN 5.1): experiences and their facts, skills, education, references. */
export function LibraryPage() {
  const [tab, setTab] = useState<Tab>("experience")
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("")
  const [track, setTrack] = useState("")
  const [reviewOnly, setReviewOnly] = useState(false)
  const [expDialog, setExpDialog] = useState<{
    exp: ExperienceOut | null
  } | null>(null)
  const [factDialog, setFactDialog] = useState<FactDialogState>(null)
  const review = useReviewFor("library")

  const experiences = useKitList<ExperienceOut>("experiences")
  const facts = useKitList<FactOut>("facts")
  const tracks = useKitList<TrackOut>("tracks")

  const visibleFacts = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (facts.data ?? []).filter(
      (f) =>
        (!status || f.status === status) &&
        (!track || (f.tracks ?? []).includes(track)) &&
        (!reviewOnly || f.review_state === "needs_review") &&
        (!q ||
          `${f.code} ${f.text} ${(f.tags ?? []).join(" ")}`
            .toLowerCase()
            .includes(q))
    )
  }, [facts.data, search, status, track, reviewOnly])

  const filtering = !!(search.trim() || status || track || reviewOnly)

  return (
    <div>
      <PageHeader
        title="Library"
        description="Facts are the unit of truth. A CV is a selection of approved facts, so everything here is something you have confirmed is true."
      />
      <ReviewBanner
        count={review.count}
        only={reviewOnly}
        onOnlyChange={setReviewOnly}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented<Tab>
          aria-label="Library section"
          className="max-w-full overflow-x-auto"
          value={tab}
          onValueChange={setTab}
          options={[
            { value: "experience", label: "Experience and facts" },
            { value: "skills", label: "Skills" },
            { value: "education", label: "Education and certificates" },
            { value: "references", label: "References" },
          ]}
        />
        <SearchBox
          value={search}
          onChange={setSearch}
          label="Search the library"
          placeholder="Search the library"
        />
        {(tab === "experience" || tab === "education") && (
          <>
            <NativeSelect
              aria-label="Filter by status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">Any status</option>
              {Object.entries(FACT_STATUS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="Filter by track"
              value={track}
              onChange={(e) => setTrack(e.target.value)}
            >
              <option value="">Any track</option>
              {(tracks.data ?? []).map((t) => (
                <option key={t.id} value={t.key}>
                  {t.name}
                </option>
              ))}
            </NativeSelect>
          </>
        )}
        <span className="ml-auto flex gap-2">
          {tab === "experience" && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setExpDialog({ exp: null })}
              >
                <Plus aria-hidden="true" />
                Add experience
              </Button>
              <Button size="sm" onClick={() => setFactDialog({ fact: null })}>
                <Plus aria-hidden="true" />
                Add fact
              </Button>
            </>
          )}
          {tab === "education" && (
            <Button
              size="sm"
              onClick={() => setFactDialog({ fact: null, kind: "education" })}
            >
              <Plus aria-hidden="true" />
              Add education or certificate
            </Button>
          )}
        </span>
      </div>

      {tab === "experience" && (
        <QueryGate query={experiences}>
          {(exps) => {
            const mine = (f: FactOut) =>
              f.kind !== "education" && f.kind !== "cert"
            const orphans = visibleFacts.filter(
              (f) => mine(f) && !exps.some((e) => e.id === f.experience_id)
            )
            const q = search.trim().toLowerCase()
            const shown = exps.filter((e) => {
              if (!filtering) return true
              const has = visibleFacts.some((f) => f.experience_id === e.id)
              const nameHit =
                !!q &&
                `${e.org} ${(e.titles ?? []).map((t) => t.title).join(" ")}`
                  .toLowerCase()
                  .includes(q)
              const reviewHit = reviewOnly && e.review_state === "needs_review"
              return has || nameHit || reviewHit
            })
            return (
              <div className="grid gap-4">
                {shown.length === 0 && orphans.length === 0 && (
                  <ListEmpty>
                    {exps.length === 0
                      ? "No experience yet. Add an employer, then the facts that are true about your time there."
                      : "Nothing matches. Clear the search or filters."}
                  </ListEmpty>
                )}
                {shown.map((e) => (
                  <ExperienceCard
                    key={e.id}
                    exp={e}
                    facts={visibleFacts.filter((f) => f.experience_id === e.id)}
                    onEdit={(x) => setExpDialog({ exp: x })}
                    onEditFact={(f) => setFactDialog({ fact: f })}
                    onAddFact={(id) =>
                      setFactDialog({ fact: null, experienceId: id })
                    }
                    empty={filtering ? "No facts match here." : "No facts yet."}
                  />
                ))}
                {orphans.length > 0 && (
                  <section
                    aria-label="Facts not tied to a role"
                    className="overflow-hidden rounded-lg border border-border bg-surface"
                  >
                    <h3 className="border-b border-border bg-surface-2 px-3.5 py-2.5 text-base font-semibold">
                      Not tied to a role
                    </h3>
                    <ul className="m-0 list-none p-0">
                      {orphans.map((f) => (
                        <FactRow
                          key={f.id}
                          fact={f}
                          onEdit={(x) => setFactDialog({ fact: x })}
                        />
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            )
          }}
        </QueryGate>
      )}

      {tab === "education" && (
        <QueryGate query={facts}>
          {() => {
            const rows = visibleFacts.filter(
              (f) => f.kind === "education" || f.kind === "cert"
            )
            return rows.length === 0 ? (
              <ListEmpty>
                No degrees or certificates{filtering ? " match" : " yet"}.
              </ListEmpty>
            ) : (
              <ul
                aria-label="Education and certificates"
                className="m-0 list-none overflow-hidden rounded-lg border border-border bg-surface p-0"
              >
                {rows.map((f) => (
                  <FactRow
                    key={f.id}
                    fact={f}
                    onEdit={(x) => setFactDialog({ fact: x })}
                  />
                ))}
              </ul>
            )
          }}
        </QueryGate>
      )}

      {tab === "skills" && (
        <SkillsTab search={search} reviewOnly={reviewOnly} />
      )}
      {tab === "references" && (
        <ReferencesTab search={search} reviewOnly={reviewOnly} />
      )}

      {expDialog && (
        <ExperienceDialog
          key={expDialog.exp?.id ?? "new"}
          open
          onOpenChange={(o) => !o && setExpDialog(null)}
          exp={expDialog.exp}
        />
      )}
      {factDialog && (
        <FactDialog
          key={factDialog.fact?.id ?? `new-${factDialog.experienceId ?? ""}`}
          open
          onOpenChange={(o) => !o && setFactDialog(null)}
          fact={factDialog.fact}
          experienceId={factDialog.experienceId}
          kind={factDialog.kind}
          experiences={experiences.data ?? []}
        />
      )}
    </div>
  )
}
