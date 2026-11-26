import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { toast } from "sonner"
import { View } from "@/components/view"
import { Chip } from "@/components/chip"
import { Input } from "@/components/ui/input"
import {
  campaignQuery,
  ck,
  facetsQuery,
  saveCampaign,
  settingsByKey,
  settingsQuery,
  tracksQuery,
  useCampaignMutations,
} from "./api"
import {
  effectiveMode,
  modeCeiling,
  pendingItems,
  toInput,
  type CampaignDraft,
  type PendingItem,
} from "./automation"
import { AutomationSection } from "./automation-section"
import {
  EditorSection,
  Field,
  NativeSelect,
  SaveIndicator,
  toneForStatus,
} from "./bits"
import { cleanConditionSet } from "./conditions"
import { ConfirmationBanner } from "./confirmation-banner"
import {
  ScheduleBudgetSection,
  SourcesSection,
  UnknownSection,
} from "./other-sections"
import { RulesSection } from "./rules-section"
import { ScoringSection } from "./scoring-section"
import { TagInput } from "./tag-input"
import { useAutosave } from "./use-autosave"
import type { Campaign } from "./types"

const SECTIONS = [
  { id: "target", label: "Target" },
  { id: "rules", label: "Rules" },
  { id: "missing", label: "Missing information" },
  { id: "scoring", label: "Scoring" },
  { id: "automation", label: "Automation" },
  { id: "sources", label: "Sources" },
  { id: "schedule", label: "Schedule and budget" },
] as const

/** What is sent to the API: drop half-filled rows so the schema is always satisfied. */
export function sanitise(d: CampaignDraft): CampaignDraft {
  const c = d.criteria ?? {}
  return {
    ...d,
    name: d.name.trim() || "Untitled campaign",
    criteria: {
      ...c,
      rules: (c.rules ?? []).map((r) => ({
        ...r,
        conditions: cleanConditionSet(r.conditions),
        points:
          r.effect === "penalty" || r.effect === "bonus"
            ? (r.points ?? 10)
            : null,
      })),
      locations: (c.locations ?? []).filter((l) => l.place.trim()),
      pay_floors: (c.pay_floors ?? []).filter(
        (f) => /^[A-Z]{3}$/.test(f.currency) && f.amount_minor > 0
      ),
    },
  }
}

export function CampaignEditorPage({ id }: { id: string }) {
  const q = useQuery(campaignQuery(id))
  if (q.isLoading)
    return (
      <View>
        <p className="text-muted-foreground">Loading the campaign...</p>
      </View>
    )
  if (q.isError || !q.data)
    return (
      <View>
        <BackLink />
        <p role="alert" className="mt-3">
          We could not open that campaign. It may have been deleted.
        </p>
      </View>
    )
  return <Editor key={id} initial={q.data} />
}

function BackLink() {
  return (
    <Link
      to="/campaigns"
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-3.5" aria-hidden="true" /> All campaigns
    </Link>
  )
}

function Editor({ initial }: { initial: Campaign }) {
  const qc = useQueryClient()
  const live = useQuery({
    ...campaignQuery(initial.id),
    initialData: initial,
  }).data
  const [draft, setDraft] = useState<CampaignDraft>(() => toInput(initial))
  const m = useCampaignMutations()
  const catalogue = useQuery(facetsQuery()).data ?? []
  const tracks = useQuery(tracksQuery()).data ?? []
  const settings = settingsByKey(useQuery(settingsQuery()).data?.groups)

  const needsReview = live.review_state !== "confirmed"
  const ceiling = modeCeiling(live)
  const ceilingRef = useRef(ceiling)
  useEffect(() => {
    ceilingRef.current = ceiling
  })
  const draftRef = useRef(draft)

  const auto = useAutosave<CampaignDraft>(async (d) => {
    const body = sanitise(d)
    // Never save a mode above what is allowed now.
    body.automation = {
      ...body.automation,
      mode: effectiveMode(body.automation?.mode, ceilingRef.current),
    }
    const saved = await saveCampaign(initial.id, body)
    qc.setQueryData(ck.campaign(initial.id), saved)
    void qc.invalidateQueries({ queryKey: ck.campaigns })
  })
  const { touch } = auto
  const edit = (patch: Partial<CampaignDraft>) => {
    const next = { ...draftRef.current, ...patch }
    draftRef.current = next
    setDraft(next)
    touch(next)
  }

  const items = useMemo(
    () => pendingItems(draft, live.unconfirmed),
    [draft, live.unconfirmed]
  )

  // Each item is confirmed on the server; the campaign is confirmed when none remain.
  const confirmItem = async (item: PendingItem["id"]) => {
    await auto.flush()
    try {
      const saved = await m.confirmItem.mutateAsync({ id: initial.id, item })
      if (saved.review_state === "confirmed")
        toast.success(
          "Campaign confirmed. Higher automation modes are unlocked."
        )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not confirm.")
    }
  }
  const editItem = (section: string) => {
    document
      .getElementById(section)
      ?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  const criteria = draft.criteria ?? {}
  const unconfirmedIds: string[] = needsReview ? live.unconfirmed : []
  const mode = effectiveMode(draft.automation?.mode, ceiling)

  return (
    <View>
      <BackLink />
      <header className="mt-2 mb-4 flex flex-wrap items-end gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-72">
          <label htmlFor="campaign-name" className="eyebrow">
            Campaign name
          </label>
          <Input
            id="campaign-name"
            className="mt-1 h-10 text-lg font-semibold"
            value={draft.name}
            onChange={(e) => edit({ name: e.target.value })}
          />
        </div>
        <Chip tone={toneForStatus[live.status]}>
          {live.status === "paused" && live.paused_until
            ? `Paused until ${live.paused_until}`
            : live.status[0].toUpperCase() + live.status.slice(1)}
        </Chip>
        <SaveIndicator
          state={auto.state}
          error={auto.error}
          needsConfirmation={needsReview}
        />
      </header>

      <nav
        aria-label="Campaign sections"
        className="sticky top-0 z-10 -mx-1 mb-5 flex [scrollbar-width:none] gap-0.5 overflow-x-auto border-b border-border bg-background px-1"
      >
        {SECTIONS.map((s, i) => (
          <button
            key={s.id}
            type="button"
            onClick={() => editItem(s.id)}
            className="-mb-px inline-flex items-center gap-1.5 border-b-2 border-transparent px-2.5 pt-2 pb-2.5 text-[0.88rem] font-semibold whitespace-nowrap text-muted-foreground hover:text-foreground"
          >
            <span className="num text-faint">{i + 1}</span>
            {s.label}
          </button>
        ))}
      </nav>

      {needsReview && (
        <div className="max-w-[860px]">
          <ConfirmationBanner
            items={items}
            busy={m.confirmItem.isPending}
            onConfirm={(i) => void confirmItem(i)}
            onEdit={(i) => editItem(i.section)}
          />
        </div>
      )}

      <div className="max-w-[860px]">
        <EditorSection
          id="target"
          number={1}
          title="Target"
          lead="What this campaign is looking for: the job titles and words that bring a role in."
        >
          <Field label="Career track" htmlFor="track">
            <NativeSelect
              id="track"
              value={draft.track_id ?? ""}
              onChange={(e) => edit({ track_id: e.target.value || null })}
            >
              <option value="">No track</option>
              {tracks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field
            label="Job titles"
            hint="A role whose title is close to any of these is picked up."
          >
            <TagInput
              label="job titles"
              values={criteria.titles ?? []}
              onChange={(titles) => edit({ criteria: { ...criteria, titles } })}
              placeholder="for example: Pricing Actuary"
            />
          </Field>
          <Field
            label="Keywords"
            hint="Words that help find roles even when the title is unusual."
          >
            <TagInput
              label="keywords"
              values={criteria.keywords ?? []}
              onChange={(keywords) =>
                edit({ criteria: { ...criteria, keywords } })
              }
              placeholder="for example: catastrophe"
            />
          </Field>
        </EditorSection>

        <EditorSection
          id="rules"
          number={2}
          title="Rules"
          lead="What to keep, what to drop, and what to rank lower. These are checked before any scoring, and a high score never rescues a role you ruled out."
        >
          <RulesSection
            campaignId={initial.id}
            criteria={criteria}
            catalogue={catalogue}
            unconfirmed={unconfirmedIds}
            onChange={(c) => edit({ criteria: c })}
          />
        </EditorSection>

        <EditorSection
          id="missing"
          number={3}
          title="When information is missing"
          lead="Postings often leave things out. Say what should happen to a role when a fact you care about is not there."
        >
          <UnknownSection
            policy={draft.unknown_data_policy ?? {}}
            onChange={(p) => edit({ unknown_data_policy: p })}
          />
        </EditorSection>

        <EditorSection
          id="scoring"
          number={4}
          title="Scoring"
          lead="How roles that pass the rules are scored from 0 to 100, and where the lines fall. Test a change on roles you have already saved before using it."
        >
          <ScoringSection
            campaignId={initial.id}
            rubricId={draft.rubric_id ?? null}
            defaults={{
              shortlist: Number(settings["scoring.threshold_shortlist"] ?? 60),
              tailor: Number(settings["scoring.threshold_tailor"] ?? 70),
              auto: Number(settings["scoring.threshold_auto_apply"] ?? 85),
            }}
            onRubricChange={(rid) => edit({ rubric_id: rid })}
          />
        </EditorSection>

        <EditorSection
          id="automation"
          number={5}
          title="Automation"
          lead="How much the system does for you. It starts at Prepare documents and only goes further when you choose."
        >
          <AutomationSection
            policy={{ ...draft.automation, mode }}
            ceiling={ceiling}
            onChange={(a) => edit({ automation: a })}
          />
          <Field
            label="If two roles score the same, prefer this level"
            htmlFor="pref-seniority"
          >
            <Input
              id="pref-seniority"
              value={draft.preferred_seniority ?? ""}
              onChange={(e) =>
                edit({ preferred_seniority: e.target.value || null })
              }
              placeholder="for example: Senior"
            />
          </Field>
        </EditorSection>

        <EditorSection
          id="sources"
          number={6}
          title="Sources"
          lead="Where this campaign looks for roles."
        >
          <SourcesSection
            selected={draft.source_ids ?? []}
            onChange={(ids) => edit({ source_ids: ids })}
          />
        </EditorSection>

        <EditorSection
          id="schedule"
          number={7}
          title="Schedule and budget"
          lead="When it runs, and how much AI work it may use."
        >
          <ScheduleBudgetSection
            cron={draft.schedule_cron ?? null}
            defaultCron={
              (settings["schedule.sweep_cron"] as string | undefined) ?? null
            }
            onCron={(c) => edit({ schedule_cron: c })}
            budget={draft.budget ?? {}}
            onBudget={(b) => edit({ budget: b })}
            currency={String(settings["budget.currency"] ?? "USD")}
          />
        </EditorSection>
      </div>
    </View>
  )
}
