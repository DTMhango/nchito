import type {
  AutomationMode,
  Campaign,
  CampaignInput,
  UnknownChoice,
} from "./types"

/** Weakest to strongest. The order is the safety order, so it is code, not a setting. */
export const MODE_ORDER: AutomationMode[] = [
  "save_only",
  "prepare",
  "ask_then_apply",
  "auto_apply",
]

export const MODES: { value: AutomationMode; label: string; line: string }[] = [
  {
    value: "save_only",
    label: "Save only",
    line: "Scores and lists roles. Nothing is written for you.",
  },
  {
    value: "prepare",
    label: "Prepare documents",
    line: "Writes your CV and letter for roles worth applying to, then waits for you.",
  },
  {
    value: "ask_then_apply",
    label: "Ask me, then apply",
    line: "Prepares everything, asks you once per application, then sends it.",
  },
  {
    value: "auto_apply",
    label: "Apply automatically",
    line: "Sends applications without asking when every safety check passes.",
  },
]

export const LOCK_REASON =
  "Locked at Prepare documents until you confirm this campaign's pay floors, countries and seniority. Nothing is sent on your behalf before then."

/**
 * The strongest mode allowed now. Until the owner has confirmed the criteria the mode is
 * capped at Prepare, whatever the server says (DESIGN 8.1: "campaign enabled and confirmed").
 */
export function modeCeiling(
  c: Pick<Campaign, "review_state" | "mode_ceiling">
): AutomationMode {
  if (c.review_state !== "confirmed") {
    const server = MODE_ORDER.indexOf(c.mode_ceiling)
    return MODE_ORDER[Math.min(server < 0 ? 1 : server, 1)]
  }
  return c.mode_ceiling
}

export const isModeAllowed = (
  mode: AutomationMode,
  ceiling: AutomationMode
): boolean => MODE_ORDER.indexOf(mode) <= MODE_ORDER.indexOf(ceiling)

/** The mode to show and save: never above the ceiling. */
export function effectiveMode(
  chosen: AutomationMode | undefined,
  ceiling: AutomationMode
): AutomationMode {
  const m = chosen ?? "prepare"
  return isModeAllowed(m, ceiling) ? m : ceiling
}

export const UNKNOWN_CHOICES: { value: UnknownChoice | ""; label: string }[] = [
  { value: "", label: "Use the general setting" },
  { value: "review", label: "Hold it for me to review" },
  { value: "pass_with_penalty", label: "Let it through with a lower score" },
  {
    value: "pass_blocks_auto",
    label: "Let it through, but never apply automatically",
  },
  { value: "fail", label: "Reject it" },
]

export const UNKNOWN_FIELDS: {
  key: "pay" | "eligibility" | "deadline"
  label: string
  plain: string
}[] = [
  {
    key: "pay",
    label: "Pay is not stated",
    plain:
      "Many postings never say what they pay. Choose what should happen to those.",
  },
  {
    key: "eligibility",
    label: "Your right to work is unclear",
    plain:
      "The posting does not say whether you can take the job from where you live, or whether they sponsor visas.",
  },
  {
    key: "deadline",
    label: "No closing date is given",
    plain:
      "Only a date that has already passed blocks a role. Choose what happens when there is no date at all.",
  },
]

export type CampaignDraft = CampaignInput

/** The editable part of a campaign, as sent to PUT. */
export function toInput(c: Campaign): CampaignDraft {
  return {
    name: c.name,
    track_id: c.track_id ?? null,
    priority: c.priority ?? 0,
    criteria: c.criteria as CampaignDraft["criteria"],
    unknown_data_policy: c.unknown_data_policy,
    rubric_id: c.rubric_id ?? null,
    automation: c.automation,
    budget: c.budget,
    source_ids: c.source_ids ?? [],
    schedule_cron: c.schedule_cron ?? null,
    preferred_seniority: c.preferred_seniority ?? null,
  }
}

export type PendingItem = {
  id: "pay_floors" | "countries" | "seniority"
  label: string
  value: string
  section: string
}

/** The items an imported campaign needs the owner to confirm (they have no defaults). */
export function pendingItems(c: CampaignDraft): PendingItem[] {
  const crit = c.criteria ?? {}
  const floors = crit.pay_floors ?? []
  const places = (crit.locations ?? []).filter((l) => l.kind !== "deny")
  const seniority = crit.seniority ?? []
  return [
    {
      id: "pay_floors",
      label: "Pay floors",
      value: floors.length
        ? floors
            .map(
              (f) =>
                `${f.currency} ${(f.amount_minor / 100).toLocaleString()} a ${f.period ?? "year"} (${f.employment_type.replace("_", " ")})`
            )
            .join(", ")
        : "Not set",
      section: "rules",
    },
    {
      id: "countries",
      label: "Countries",
      value: places.length ? places.map((l) => l.place).join(", ") : "Not set",
      section: "rules",
    },
    {
      id: "seniority",
      label: "Seniority",
      value: seniority.length ? seniority.join(", ") : "Not set",
      section: "rules",
    },
  ]
}
