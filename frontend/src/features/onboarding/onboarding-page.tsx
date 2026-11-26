import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import {
  Check,
  FlaskConical,
  Mail,
  Palette,
  Radar,
  Scale,
  Sparkles,
  Target,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { BrandMark } from "@/components/brand-mark"
import { useAppName } from "@/lib/use-app-name"
import { cn } from "@/lib/utils"
import { onboardingKey, useServerProgress } from "./api"
import { useLocalOnboarding } from "./state"
import { StartStep } from "./steps/start-step"
import { YouStep } from "./steps/you-step"
import { TracksStep } from "./steps/tracks-step"
import { CriteriaStep } from "./steps/criteria-step"
import {
  DryRunStep,
  LookStep,
  MailStep,
  SourcesStep,
} from "./steps/later-steps"

type Step = { n: number; title: string; icon: LucideIcon; lead: string }

/** The set-up guide (DESIGN 13). Resumable at any step, every step skippable. */
export const STEPS: Step[] = [
  {
    n: 1,
    title: "How to start",
    icon: Sparkles,
    lead: "Start empty, or bring in a kit file, a shareable template or your old job-hunting folder. You see what would change before anything is saved.",
  },
  {
    n: 2,
    title: "About you",
    icon: UserRound,
    lead: "Your name and contact details, and one true sentence. Facts you add are drafts until you approve them.",
  },
  {
    n: 3,
    title: "Tracks",
    icon: Target,
    lead: "The kinds of role you go for. Each can have its own search later.",
  },
  {
    n: 4,
    title: "Criteria",
    icon: Scale,
    lead: "Pay floor, countries, seniority, work rights and relocation. No value is pre-filled: enter each one, or decide later.",
  },
  {
    n: 5,
    title: "Sources",
    icon: Radar,
    lead: "Where to look for roles. Switch on the boards you want searched.",
  },
  {
    n: 6,
    title: "Mailbox (optional)",
    icon: Mail,
    lead: "Lets the app send applications by email and spot replies. You can skip it.",
  },
  {
    n: 7,
    title: "First dry run",
    icon: FlaskConical,
    lead: "Look at scored results before anything is switched on. A dry run sends nothing.",
  },
  {
    n: 8,
    title: "Look and feel",
    icon: Palette,
    lead: "Pick a theme. Change it any time under Settings.",
  },
]

export function OnboardingPage({ step }: { step: number }) {
  const navigate = useNavigate()
  const appName = useAppName()
  const [local, update] = useLocalOnboarding()
  const server = useServerProgress()
  const qc = useQueryClient()
  // Each step can change what exists, so ask the server again whenever the step changes.
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: onboardingKey })
  }, [qc, step])
  const current = STEPS.find((s) => s.n === step) ?? STEPS[0]
  const go = (n: number) => navigate({ to: "/onboarding", search: { step: n } })
  const next = () => go(Math.min(current.n + 1, STEPS.length))
  const skip = () => {
    if (!local.skipped.includes(current.n))
      update({ skipped: [...local.skipped, current.n] })
    next()
  }

  // Done only when the server says so. A skipped step is not done (unknown is not yes).
  const done: Record<number, boolean> = {
    1: server.kit,
    2: server.facts,
    3: server.tracks,
    4: server.criteria,
    5: server.sources,
    6: server.mail,
    7: server.dryRun,
    8: local.skipped.includes(8) || step === 8,
  }
  const finished = STEPS.filter((s) => done[s.n]).length

  return (
    <div className="min-h-dvh bg-background">
      <header className="flex items-center gap-3 border-b border-border px-4 py-3 sm:px-8">
        <BrandMark />
        <span className="heading text-[1.1rem] font-bold">{appName}</span>
        <span className="text-muted-foreground max-sm:hidden">
          · Set-up guide
        </span>
        <span
          className="ml-auto num text-sm text-muted-foreground"
          role="status"
          aria-label="Progress"
        >
          {server.loading
            ? "Checking progress"
            : server.error
              ? "Progress unknown"
              : server.complete
                ? `Set-up complete, ${finished} of ${STEPS.length} done`
                : `${finished} of ${STEPS.length} done`}
        </span>
        <Button asChild variant="ghost" size="sm">
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
              const isDone = done[s.n]
              const active = s.n === current.n
              return (
                <li key={s.n} className="max-md:shrink-0">
                  <button
                    type="button"
                    onClick={() => go(s.n)}
                    aria-current={active ? "step" : undefined}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-sm px-2.5 py-2 text-left font-medium text-muted-foreground hover:bg-sunken hover:text-foreground",
                      active &&
                        "bg-surface text-foreground shadow-sm outline-1 -outline-offset-1 outline-border"
                    )}
                  >
                    <span
                      className={cn(
                        "grid size-6 shrink-0 place-items-center rounded-full border num text-xs",
                        isDone && "border-good bg-good-soft text-good",
                        active &&
                          !isDone &&
                          "border-primary bg-primary text-primary-foreground",
                        !isDone && !active && "border-border-strong"
                      )}
                    >
                      {isDone ? (
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
          {server.next && (
            <p
              data-testid="next-step"
              className="rounded-sm bg-sunken px-3 py-2 text-sm"
            >
              <span className="font-semibold">Still to do: </span>
              {server.next.label}. {server.next.detail}
            </p>
          )}

          {current.n === 1 && (
            <StartStep local={local} update={update} next={next} />
          )}
          {current.n === 2 && <YouStep next={next} />}
          {current.n === 3 && <TracksStep next={next} />}
          {current.n === 4 && (
            <CriteriaStep local={local} update={update} next={next} />
          )}
          {current.n === 5 && <SourcesStep next={next} />}
          {current.n === 6 && <MailStep next={next} skip={skip} />}
          {current.n === 7 && <DryRunStep local={local} next={next} />}
          {current.n === 8 && <LookStep />}

          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-5">
            {current.n > 1 && (
              <Button variant="outline" onClick={() => go(current.n - 1)}>
                Back
              </Button>
            )}
            <span className="flex-1" />
            {current.n < STEPS.length ? (
              <Button variant="ghost" onClick={skip}>
                Skip for now
              </Button>
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
