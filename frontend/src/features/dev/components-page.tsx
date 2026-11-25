import { useState, type ReactNode } from "react"
import {
  CalendarClock,
  HelpCircle,
  Inbox,
  Lock,
  Mail,
  Send,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { ApprovalReceipt } from "@/components/approval-receipt"
import { Chip, FilterChip, type FilterState } from "@/components/chip"
import { DataTable } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
import { EvidencePopover } from "@/components/evidence-popover"
import { FactTag } from "@/components/fact-tag"
import { FunnelStrip } from "@/components/funnel-strip"
import { KanbanBoard, KanbanCard } from "@/components/kanban-board"
import { KeyHint } from "@/components/key-hint"
import { PageHeader, SectionHeader } from "@/components/page-header"
import { PaperPage, PaperPreview } from "@/components/paper-preview"
import { ScoreRing } from "@/components/score-ring"
import { Segmented } from "@/components/segmented"
import { SeverityItem } from "@/components/severity-item"
import { SplitView } from "@/components/split-view"
import { Sparkbar } from "@/components/sparkbar"
import { StagePill, STAGES } from "@/components/stage-pill"
import { ThresholdTrack, type Thresholds } from "@/components/threshold-track"
import { View } from "@/components/view"
import { WhyPanel } from "@/components/why-panel"
import { BOARD_COLUMNS } from "@/features/applications/applications-page"
import {
  SAMPLE_CARDS,
  SAMPLE_FACTS,
  SAMPLE_FUNNEL,
  SAMPLE_SCORES,
  SAMPLE_SPARK,
  SAMPLE_WHY,
} from "@/mocks/fixtures/gallery"
import { ThemeScope } from "@/themes/scope"
import { useTheme } from "@/themes/provider"
import type { Mode } from "@/themes/schema"

type ModeChoice = "current" | "light" | "dark"

/** Dev-only gallery: every shared component, rendered in every theme. */
export function ComponentsPage() {
  const { themes, mode } = useTheme()
  const [which, setWhich] = useState<string>("all")
  const [modeChoice, setModeChoice] = useState<ModeChoice>("current")
  const m: Mode = modeChoice === "current" ? mode : modeChoice
  const shown = which === "all" ? themes : themes.filter((t) => t.id === which)

  return (
    <View>
      <PageHeader
        eyebrow="Development"
        title="Component gallery"
        description="Shared components for later waves, each rendered inside a theme scope. Sample content is fictional."
        actions={
          <>
            <Segmented
              aria-label="Theme"
              size="sm"
              value={which}
              onValueChange={setWhich}
              options={[
                { value: "all", label: "All" },
                ...themes.map((t) => ({ value: t.id, label: t.name })),
              ]}
            />
            <Segmented<ModeChoice>
              aria-label="Mode"
              size="sm"
              value={modeChoice}
              onValueChange={setModeChoice}
              options={[
                { value: "current", label: "Current" },
                { value: "light", label: "Light" },
                { value: "dark", label: "Dark" },
              ]}
            />
          </>
        }
      />
      <div className="grid gap-8">
        {shown.map((t) => (
          <ThemeScope
            key={t.id}
            theme={t}
            mode={m}
            className="rounded-xl border border-border p-5"
          >
            <div className="mb-4 flex items-baseline gap-3">
              <h2 className="text-xl">{t.name}</h2>
              <span className="text-sm text-faint">
                {m} · {t.fonts.display}, {t.fonts.body}
              </span>
            </div>
            <Gallery />
          </ThemeScope>
        ))}
      </div>
    </View>
  )
}

function Block({
  title,
  children,
  wide,
}: {
  title: string
  children: ReactNode
  wide?: boolean
}) {
  return (
    <section
      className={
        wide ? "grid gap-2.5 lg:col-span-2" : "grid content-start gap-2.5"
      }
    >
      <div className="eyebrow">{title}</div>
      {children}
    </section>
  )
}

function Gallery() {
  const [filters, setFilters] = useState<Record<string, FilterState>>({
    a: "include",
    b: "exclude",
    c: "off",
  })
  const [cards, setCards] = useState(SAMPLE_CARDS)
  const [thr, setThr] = useState<Thresholds>({
    shortlist: 60,
    tailor: 70,
    auto: 85,
  })
  const [seg, setSeg] = useState("board")
  const [detail, setDetail] = useState(false)

  return (
    <div className="grid gap-7 lg:grid-cols-2">
      <Block title="Buttons and key hints">
        <div className="flex flex-wrap items-center gap-2">
          <Button>
            Tailor <KeyHint keys="T" tone="inverse" />
          </Button>
          <Button variant="outline">
            Skip <KeyHint keys="S" />
          </Button>
          <Button variant="ghost">Pin</Button>
          <Button variant="destructive">Withdraw</Button>
          <KeyHint keys="Mod K" />
        </div>
      </Block>

      <Block title="ScoreRing">
        <div className="flex items-center gap-3">
          <ScoreRing score={42} />
          <ScoreRing score={74} />
          <ScoreRing score={91} />
          <ScoreRing score={88} size={88} />
        </div>
      </Block>

      <Block title="Chip and three-state FilterChip">
        <div className="flex flex-wrap gap-1.5">
          <Chip>Neutral</Chip>
          <Chip tone="good">Applied 2</Chip>
          <Chip tone="warn">Sign in</Chip>
          <Chip tone="danger">Failed</Chip>
          <Chip tone="info">Interview Fri</Chip>
          <Chip tone="accent">12 new</Chip>
          <Chip tone="primary">In use</Chip>
          <Chip tone="line">Rolling</Chip>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {[
            ["a", "Sponsorship offered"],
            ["b", "Not stated"],
            ["c", "Remote worldwide"],
          ].map(([id, label]) => (
            <FilterChip
              key={id}
              label={label}
              facet="Visa"
              state={filters[id]}
              count={7}
              onStateChange={(s) => setFilters((f) => ({ ...f, [id]: s }))}
            />
          ))}
        </div>
      </Block>

      <Block title="StagePill">
        <div className="flex flex-wrap gap-1.5">
          {STAGES.map((s) => (
            <StagePill key={s} stage={s} />
          ))}
        </div>
      </Block>

      <Block title="SeverityStripe list item" wide>
        <div className="elev py-1.5">
          <SeverityItem
            severity="good"
            icon={Send}
            title="Approve application"
            meta="Kafue Analytics · Head of Data · score 88"
            age="12 min ago"
            actions={
              <>
                <Button variant="ghost" size="sm">
                  Skip
                </Button>
                <Button size="sm">Review</Button>
              </>
            }
          />
          <SeverityItem
            severity="danger"
            icon={Lock}
            title="Sign in needed"
            meta="Sample Re · portal · signing in unlocks 2 applications"
            age="2 h ago"
            actions={<Button size="sm">Open portal</Button>}
          />
          <SeverityItem
            severity="info"
            icon={HelpCircle}
            title="New question"
            meta="One work-rights answer affects four roles"
            actions={<Button size="sm">Answer</Button>}
          />
          <SeverityItem
            severity="warn"
            icon={Mail}
            title="Confirm submission"
            meta="No confirmation email after 24 h"
            actions={<Button size="sm">Mark as submitted</Button>}
          />
        </div>
      </Block>

      <Block title="PageHeader and EmptyState">
        <div className="panel p-4">
          <PageHeader
            title="Head of Data"
            eyebrow="Kafue Analytics · Remote"
            meta={<StagePill stage="ready" />}
            className="mb-0"
          />
        </div>
        <div className="panel">
          <EmptyState
            icon={Inbox}
            title="No new matches"
            description="Roles from each sweep land here."
            actions={<Button size="sm">Add job</Button>}
          />
        </div>
      </Block>

      <Block title="FactTag and EvidencePopover">
        <p className="leading-loose">
          Line manager for six people{" "}
          <FactTag code="F-107" text={SAMPLE_FACTS["F-107"]} />, built a
          modelling platform{" "}
          <FactTag code="F-104" text={SAMPLE_FACTS["F-104"]} status="draft" />.
        </p>
        <p>
          Visa sponsorship:{" "}
          <EvidencePopover
            title="From the posting"
            content="“We sponsor work permits for this role.”"
            source="Posting, paragraph 4"
            triggerClassName="underline decoration-dotted underline-offset-4"
          >
            <Chip tone="good">yes</Chip>
          </EvidencePopover>
        </p>
      </Block>

      <Block title="FunnelStrip" wide>
        <FunnelStrip steps={SAMPLE_FUNNEL} />
      </Block>

      <Block title="Sparkbar">
        <Sparkbar
          values={SAMPLE_SPARK}
          edgeLabels={["12 Nov", "25 Nov"]}
          label="Applications sent per day"
          unit="sent"
        />
      </Block>

      <Block title="SegmentedMode">
        <Segmented
          aria-label="Layout"
          value={seg}
          onValueChange={setSeg}
          options={[
            { value: "board", label: "Board" },
            { value: "table", label: "Table" },
            { value: "both", label: "Both" },
          ]}
        />
      </Block>

      <Block title="ThresholdTrack" wide>
        <div className="elev p-5">
          <ThresholdTrack
            scores={SAMPLE_SCORES}
            value={thr}
            onValueChange={setThr}
            summary={(v, c) => (
              <>
                At <b className="num text-highlight-ink">{v.auto}</b>,{" "}
                <b className="num text-highlight-ink">{c.auto}</b> of these{" "}
                {SAMPLE_SCORES.length} roles would have come to you ready for
                one-tap approval.
              </>
            )}
          />
        </div>
      </Block>

      <Block title="KanbanBoard (drag, or arrow keys)" wide>
        <KanbanBoard
          columns={BOARD_COLUMNS}
          items={cards}
          getId={(c) => c.id}
          getColumn={(c) => (c.stage === "submitted" ? "submitted" : c.stage)}
          getLabel={(c) => `${c.employer}, ${c.role}, score ${c.score}`}
          onMove={(id, to) =>
            setCards((cs) =>
              cs.map((c) =>
                c.id === id ? { ...c, stage: to as typeof c.stage } : c
              )
            )
          }
          renderCard={(c) => (
            <KanbanCard>
              <div className="flex items-start gap-2.5">
                <div className="min-w-0 flex-1">
                  <div className="eyebrow">{c.employer}</div>
                  <div className="mt-0.5 leading-[1.3] font-semibold">
                    {c.role}
                  </div>
                </div>
                <ScoreRing score={c.score} size={32} />
              </div>
              <div
                className={
                  c.due
                    ? "flex items-center gap-1.5 border-t border-dashed border-border pt-1.75 text-xs text-warn"
                    : "flex items-center gap-1.5 border-t border-dashed border-border pt-1.75 text-xs text-muted-foreground"
                }
              >
                <CalendarClock className="size-3.5" aria-hidden="true" />
                {c.next}
              </div>
            </KanbanCard>
          )}
        />
      </Block>

      <Block title="DataTable" wide>
        <DataTable
          rows={cards}
          getRowId={(c) => c.id}
          caption="Sample applications"
          columns={[
            {
              id: "employer",
              header: "Company",
              cell: (c) => <b className="font-semibold">{c.employer}</b>,
              sortValue: (c) => c.employer,
            },
            { id: "role", header: "Role", cell: (c) => c.role },
            {
              id: "stage",
              header: "Stage",
              cell: (c) => <StagePill stage={c.stage} />,
            },
            {
              id: "score",
              header: "Score",
              cell: (c) => <ScoreRing score={c.score} size={28} />,
              sortValue: (c) => c.score,
            },
          ]}
        />
      </Block>

      <Block title="SplitView (list → detail on phones)" wide>
        <div className="h-56 rounded-lg border border-border">
          <SplitView
            showDetail={detail}
            onBack={() => setDetail(false)}
            list={
              <ul>
                {cards.slice(0, 3).map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => setDetail(true)}
                      className="grid w-full grid-cols-[36px_minmax(0,1fr)] items-center gap-3 border-b border-border px-3 row-pad text-left hover:bg-surface-2"
                    >
                      <ScoreRing score={c.score} />
                      <span className="truncate font-semibold">{c.role}</span>
                    </button>
                  </li>
                ))}
              </ul>
            }
            detail={
              <p className="text-muted-foreground">
                Detail for the selected role.
              </p>
            }
          />
        </div>
      </Block>

      <Block title="WhyPanel">
        <WhyPanel
          decision="Waiting for you"
          decisionTone="warn"
          reasons={SAMPLE_WHY}
          toProceed={[
            "Answer the work-rights question once.",
            "Or lower the auto-apply line to 79.",
          ]}
        />
        <WhyPanel reasons={[]} />
      </Block>

      <Block title="A4 Paper preview (always white)">
        <PaperPreview className="max-h-[420px] min-h-0">
          <PaperPage pageLabel="1 / 1">
            <h3>Chanda</h3>
            <p className="text-paper-muted">Head of Data · Lusaka, Zambia</p>
            <h4>Experience</h4>
            <ul>
              <li>
                Lead a team of six across analytics, BI and data engineering.
              </li>
              <li>Built the group's risk modelling platform end to end.</li>
            </ul>
          </PaperPage>
        </PaperPreview>
      </Block>

      <Block title="ApprovalReceipt (layout shell)" wide>
        <ApprovalReceipt
          employer="Kafue Analytics"
          role="Head of Data"
          destination={{
            kind: "web",
            value: "careers.example.com",
            verified: true,
          }}
          packetVersion="packet v2"
          pay="$150k to $180k"
          answers={[
            {
              question: "Salary expectation",
              answer: "Top half of the advertised range",
              material: true,
            },
            {
              question: "Do you need visa sponsorship?",
              answer: "Yes, an employment visa",
              material: true,
            },
            { question: "Notice period", answer: "3 months" },
          ]}
          attachments={[
            { name: "CV-Kafue-Analytics.pdf", kind: "pdf", hash: "3f9a…c21" },
            {
              name: "Letter-Kafue-Analytics.pdf",
              kind: "pdf",
              hash: "81d0…7be",
            },
          ]}
          disclosures={["A referee's contact details are included."]}
          changes={[
            { field: "Notice period", from: "1 month", to: "3 months" },
          ]}
          approveLabel="Let the agent submit"
          footnote="The agent must obtain a one-time permit before it clicks Submit."
        />
      </Block>

      <Block title="Section header">
        <SectionHeader
          title="Coming up"
          aside="Next two weeks"
          action={<a href="#top">See all</a>}
        />
      </Block>
    </div>
  )
}
