/** Plain-language names for Kit values, from the owner's side ("Only me", not "owner_only"). */
import type {
  AnswerOut,
  FactOut,
  GuardrailOut,
  GuardrailScope,
  ReferenceOut,
  SkillOut,
  VaultDocumentOut,
} from "./api"

export const FACT_KINDS: Record<FactOut["kind"], string> = {
  bullet: "Bullet",
  achievement: "Achievement",
  metric: "Metric",
  summary: "Summary",
  education: "Education",
  cert: "Certificate",
  project: "Project",
  speaking: "Speaking",
}

export const FACT_STATUS: Record<FactOut["status"], string> = {
  draft: "Draft",
  approved: "Approved",
  retired: "Retired",
}

export const CLAIMS: Record<NonNullable<SkillOut["claim"]>, string> = {
  yes: "Yes, claim it",
  no: "No",
  never: "Never claim",
}

export const SHARE_POLICY: Record<
  NonNullable<ReferenceOut["share_policy"]>,
  string
> = {
  on_cv: "Name on the CV",
  on_request: "Only when asked",
  forms_only: "Application forms only",
}

export const ANSWER_CLASS: Record<
  NonNullable<AnswerOut["answer_class"]>,
  { label: string; hint: string }
> = {
  auto: { label: "Use automatically", hint: "Reused on every form that asks." },
  ask_first: {
    label: "Ask me first",
    hint: "You confirm each time, until you mark it settled.",
  },
  never: { label: "Never answer", hint: "Declined, or Prefer not to say." },
  owner_only: { label: "Only me", hint: "Only you may answer these." },
}

export const ANSWER_SCOPE: Record<NonNullable<AnswerOut["scope"]>, string> = {
  this_application: "This application only",
  this_employer: "This employer",
  this_country: "This country",
  all_matching: "All matching roles",
}

export const VALUE_TYPES: Record<
  NonNullable<AnswerOut["value_type"]>,
  string
> = {
  text: "Text",
  number: "Number",
  boolean: "Yes or no",
  choice: "Pick one",
  date: "Date",
  money: "Money",
}

export const DOC_TYPES: Record<VaultDocumentOut["doc_type"], string> = {
  cv: "CV",
  degree: "Degree",
  transcript: "Transcript",
  id: "ID",
  photo: "Photo",
  cert: "Certificate",
  other: "Other",
}

export const SENSITIVITY: Record<
  VaultDocumentOut["sensitivity"],
  { label: string; hint: string }
> = {
  normal: { label: "Normal", hint: "May be attached when a role asks." },
  on_request: { label: "On request", hint: "Sent only when an employer asks." },
  after_offer_only: {
    label: "After an offer only",
    hint: "Never sent before an offer.",
  },
}

export const STRICTNESS: Record<
  NonNullable<GuardrailOut["strictness"]>,
  { label: string; hint: string }
> = {
  always_block: { label: "Always block", hint: "No waiver, ever." },
  block_waivable_once: {
    label: "Block, waivable once",
    hint: "You can allow it for one application, with a reason.",
  },
  advise: { label: "Advise", hint: "A warning only." },
}

export const SCOPES: Record<GuardrailScope, string> = {
  cv: "CV",
  letter: "Letter",
  email: "Email",
  form_answers: "Form answers",
  everywhere: "Everywhere",
}

export const GUARDRAIL_TYPES = [
  "never_mention",
  "never_together",
  "require_wording",
  "reframe",
  "omit_field",
  "format",
  "positioning",
  "limit",
  "attach_policy",
] as const
export type GuardrailType = (typeof GUARDRAIL_TYPES)[number]

export const GUARDRAIL_TYPE_LABEL: Record<
  GuardrailType,
  { label: string; blurb: string }
> = {
  never_mention: {
    label: "Never mention",
    blurb: "Terms or patterns that must never appear.",
  },
  never_together: {
    label: "Never together",
    blurb: "Two things that must not appear in the same packet.",
  },
  require_wording: {
    label: "Required wording",
    blurb: "Use one wording, not another.",
  },
  reframe: { label: "Reframe", blurb: "Prefer one phrasing over another." },
  omit_field: {
    label: "Leave out of the CV",
    blurb: "Fields that never go on a CV.",
  },
  format: { label: "Format", blurb: "How figures and dates are written." },
  positioning: {
    label: "Positioning",
    blurb: "How to pitch you, in plain words.",
  },
  limit: { label: "Length limit", blurb: "Pages and paragraphs per document." },
  attach_policy: {
    label: "Attach policy",
    blurb: "When a kind of document may be attached.",
  },
}

const list = (xs: string[] | undefined, max = 3) => {
  const v = xs ?? []
  const shown = v.slice(0, max).map((x) => `"${x}"`)
  return (
    shown.join(", ") + (v.length > max ? ` and ${v.length - max} more` : "")
  )
}

const DOC_WORD = { cv: "CVs", letter: "letters", email: "emails" } as const
const WHEN = {
  never: "never",
  when_asked: "only when asked",
  after_offer: "only after an offer",
} as const

/** One plain sentence for a guardrail ("Never mention X in CVs"). */
export function summarise(g: GuardrailOut): string {
  const p = g.params as Record<string, unknown>
  const where =
    !g.scope || g.scope.length === 0 || g.scope.includes("everywhere")
      ? "anywhere"
      : "in " +
        g.scope
          .map((s) => (s === "cv" ? "CV" : SCOPES[s].toLowerCase()))
          .join(" and ")
  switch (p.type) {
    case "never_mention": {
      const terms = [
        ...((p.terms as string[]) ?? []),
        ...((p.regex as string[]) ?? []).map((r) => `/${r}/`),
      ]
      return `Never mention ${list(terms)} ${where}.`
    }
    case "never_together":
      return `Never use ${list(p.group_a as string[])} together with ${list(p.group_b as string[])}.`
    case "require_wording":
      return `Say "${String(p.use)}", not ${list(p.instead_of as string[])}.`
    case "reframe":
      return `Prefer "${String(p.prefer)}" over "${String(p.over)}".`
    case "omit_field":
      return `Leave ${list(p.fields as string[], 4)} off the CV.`
    case "format":
      return String(p.rule ?? "A format rule.")
    case "positioning":
      return String(p.instruction ?? "A positioning note.")
    case "limit": {
      const bits = [
        p.pages ? `${String(p.pages)} page${p.pages === 1 ? "" : "s"}` : null,
        p.paragraphs ? `${String(p.paragraphs)} paragraphs` : null,
      ].filter(Boolean)
      return `${DOC_WORD[p.document as keyof typeof DOC_WORD] ?? "Documents"}: at most ${bits.join(" and ") || "no set length"}.`
    }
    case "attach_policy":
      return `Attach ${String(p.document_type)} ${WHEN[p.when as keyof typeof WHEN] ?? ""}.`.replace(
        "  ",
        " "
      )
    default:
      return g.name
  }
}

export const csv = (xs: string[] | undefined) => (xs ?? []).join(", ")
export const parseCsv = (s: string) =>
  s
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean)

export const fmtDate = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : ""

export const fmtBytes = (n: number) =>
  n < 1024
    ? `${n} B`
    : n < 1024 * 1024
      ? `${Math.round(n / 1024)} KB`
      : `${(n / 1024 / 1024).toFixed(1)} MB`
