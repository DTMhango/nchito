import { Link, useNavigate } from "@tanstack/react-router"
import {
  Check,
  Cpu,
  FileUp,
  ListChecks,
  Palette,
  Target,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { BrandMark } from "@/components/brand-mark"
import { EmptyState } from "@/components/empty-state"
import { ThemeSwatch } from "@/features/settings/theme-swatch"
import { useTheme } from "@/themes/provider"
import { useAppName } from "@/lib/use-app-name"
import { cn } from "@/lib/utils"

type Step = {
  n: number
  title: string
  icon: LucideIcon
  lead: string
  points: string[]
}

/** The set-up guide (DESIGN 13). Resumable at any step. */
export const STEPS: Step[] = [
  {
    n: 1,
    title: "Owner account",
    icon: UserRound,
    lead: "Your sign-in and time zone.",
    points: ["Done when you created your account."],
  },
  {
    n: 2,
    title: "AI",
    icon: Cpu,
    lead: "Paste a provider key, test it, and set a monthly cap. Nothing paid runs without a cap.",
    points: [
      "Anthropic API by default, or an OpenAI-compatible endpoint.",
      "The key is encrypted at rest and never shown again in full.",
      "A test call confirms it works before it is saved.",
    ],
  },
  {
    n: 3,
    title: "Bring your material",
    icon: FileUp,
    lead: "Upload CVs, a profile document, or an old kit zip. Everything is extracted into drafts.",
    points: [
      "An old kit's known files are parsed by code, not a model.",
      "Referee contacts and ID documents are held back from any model.",
      "Nothing imported can drive automation until you confirm it.",
    ],
  },
  {
    n: 4,
    title: "Review",
    icon: ListChecks,
    lead: "A guided pass over everything marked needs review, stale items first.",
    points: [
      "Pay floors, countries, seniority, visa and relocation answers first.",
      "Each item: Confirm, Edit or Drop.",
      "Conflicts between old files are shown side by side.",
    ],
  },
  {
    n: 5,
    title: "First campaign",
    icon: Target,
    lead: "Confirm criteria, pick sources, and run a dry run to look at scored results before anything is switched on.",
    points: [
      "Starts in Prepare mode: documents are tailored, nothing is sent.",
      "Raise the mode later, deliberately, from Autopilot.",
    ],
  },
  {
    n: 6,
    title: "Appearance and notifications",
    icon: Palette,
    lead: "Pick a theme and where you want to hear about things that need you.",
    points: ["Change either any time under Settings."],
  },
]

export function OnboardingPage({ step }: { step: number }) {
  const navigate = useNavigate()
  const appName = useAppName()
  const current = STEPS.find((s) => s.n === step) ?? STEPS[1]
  const go = (n: number) => navigate({ to: "/onboarding", search: { step: n } })

  return (
    <div className="min-h-dvh bg-background">
      <header className="flex items-center gap-3 border-b border-border px-4 py-3 sm:px-8">
        <BrandMark />
        <span className="heading text-[1.1rem] font-bold">{appName}</span>
        <span className="text-muted-foreground max-sm:hidden">
          · Set-up guide
        </span>
        <Button asChild variant="ghost" size="sm" className="ml-auto">
          <Link to="/today">
            <X data-icon="inline-start" aria-hidden="true" />
            Finish later
          </Link>
        </Button>
      </header>

      <div className="mx-auto grid max-w-[1040px] gap-8 px-4 py-8 sm:px-8 md:grid-cols-[240px_minmax(0,1fr)]">
        <nav aria-label="Set-up steps">
          <ol className="grid gap-1 max-md:flex max-md:overflow-x-auto">
            {STEPS.map((s) => {
              const done = s.n < current.n || s.n === 1
              const active = s.n === current.n
              return (
                <li key={s.n} className="max-md:shrink-0">
                  <button
                    type="button"
                    onClick={() => go(s.n)}
                    aria-current={active ? "step" : undefined}
                    disabled={s.n === 1}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-sm px-2.5 py-2 text-left font-medium text-muted-foreground hover:bg-sunken hover:text-foreground disabled:cursor-default disabled:hover:bg-transparent",
                      active &&
                        "bg-surface text-foreground shadow-sm outline-1 -outline-offset-1 outline-border"
                    )}
                  >
                    <span
                      className={cn(
                        "grid size-6 shrink-0 place-items-center rounded-full border num text-xs",
                        done && "border-good bg-good-soft text-good",
                        active &&
                          !done &&
                          "border-primary bg-primary text-primary-foreground",
                        !done && !active && "border-border-strong"
                      )}
                    >
                      {done ? (
                        <Check className="size-3.5" aria-label="done" />
                      ) : (
                        s.n
                      )}
                    </span>
                    <span className="max-md:hidden">{s.title}</span>
                  </button>
                </li>
              )
            })}
          </ol>
        </nav>

        <main className="grid content-start gap-6">
          <div className="grid gap-2">
            <div className="eyebrow">
              Step {current.n} of {STEPS.length}
            </div>
            <h1 className="flex items-center gap-2.5 text-2xl">
              <current.icon
                className="size-6 text-primary-ink"
                strokeWidth={1.5}
                aria-hidden="true"
              />
              {current.title}
            </h1>
            <p className="max-w-[60ch] text-muted-foreground">{current.lead}</p>
          </div>

          <ul className="grid max-w-[60ch] gap-2">
            {current.points.map((p) => (
              <li key={p} className="flex gap-2.5">
                <Check
                  className="mt-0.5 size-4 shrink-0 text-good"
                  aria-hidden="true"
                />
                {p}
              </li>
            ))}
          </ul>

          {current.n === 6 ? (
            <ThemeStep />
          ) : (
            <div className="rounded-lg border border-dashed border-border-strong">
              <EmptyState
                icon={current.icon}
                title="This step's form is on its way"
                description="The guide remembers where you are. Skip ahead and come back to it from Today or the command palette (Ctrl K)."
              />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-5">
            {current.n > 2 && (
              <Button variant="outline" onClick={() => go(current.n - 1)}>
                Back
              </Button>
            )}
            <span className="flex-1" />
            {current.n < STEPS.length ? (
              <Button onClick={() => go(current.n + 1)}>Skip for now</Button>
            ) : (
              <Button asChild>
                <Link to="/today">Go to Today</Link>
              </Button>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}

function ThemeStep() {
  const { themes, theme, setAppearance } = useTheme()
  return (
    <div className="grid gap-2">
      <div className="eyebrow">Theme</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {themes.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-pressed={t.id === theme.id}
            onClick={() => setAppearance({ theme_id: t.id })}
            className="flex items-center gap-2 rounded-sm border border-border bg-surface px-2.5 py-2 text-left font-medium aria-pressed:border-primary aria-pressed:shadow-[0_0_0_2px_var(--t-ring)]"
          >
            <ThemeSwatch theme={t} />
            {t.name}
          </button>
        ))}
      </div>
    </div>
  )
}
