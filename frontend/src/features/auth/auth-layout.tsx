import type { ReactNode } from "react"
import {
  CheckCheck,
  FileCheck2,
  Filter,
  Radar,
  Send,
  ShieldCheck,
} from "lucide-react"
import { BrandMark } from "@/components/brand-mark"
import { ScoreRing } from "@/components/score-ring"
import { DEFAULT_APP_NAME } from "@/lib/use-app-name"

const FLOW = [
  {
    icon: Radar,
    title: "Sweeps your sources",
    body: "Boards, careers pages and alert emails, on a schedule.",
  },
  {
    icon: Filter,
    title: "Filters and scores",
    body: "Your rules first, then a score with the evidence behind it.",
  },
  {
    icon: FileCheck2,
    title: "Tailors from your facts",
    body: "Every line of a CV traces back to something you approved.",
  },
  {
    icon: ShieldCheck,
    title: "Checks before anything leaves",
    body: "Guardrails run in code, then a second pass looks for claims.",
  },
  {
    icon: Send,
    title: "Applies when you say so",
    body: "Nothing is submitted without your rules or your approval.",
  },
]

/**
 * Frame for first-run setup and sign-in. Left: what the app does, in its own visual
 * language. Right: the form. Collapses to the form alone on small screens.
 */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-dvh grid-cols-1 bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <aside className="relative hidden overflow-hidden border-r border-border bg-sunken px-12 py-11 lg:flex lg:flex-col">
        <div className="flex items-center gap-2.5">
          <BrandMark />
          <span className="heading text-[1.2rem] font-bold">
            {DEFAULT_APP_NAME}
          </span>
        </div>
        <div className="my-auto grid max-w-[440px] gap-7 py-10">
          <div className="grid gap-2.5">
            <h2 className="text-[2.1rem] leading-[1.1]">
              A calm cockpit for your job hunt.
            </h2>
            <p className="text-muted-foreground">
              It finds the roles, does the paperwork and tells you only what
              needs you. Private to you, running on your own machine or server.
            </p>
          </div>
          <ol className="grid">
            {FLOW.map((f, i) => (
              <li
                key={f.title}
                className="relative grid grid-cols-[34px_minmax(0,1fr)] gap-3 pb-4 last:pb-0"
              >
                {i < FLOW.length - 1 && (
                  <span
                    aria-hidden="true"
                    className="absolute top-9 bottom-0 left-[16.5px] w-px bg-border-strong"
                  />
                )}
                <span className="z-10 grid size-[34px] place-items-center rounded-sm border border-border bg-surface text-primary-ink">
                  <f.icon
                    className="size-[18px]"
                    strokeWidth={1.5}
                    aria-hidden="true"
                  />
                </span>
                <div className="pt-1">
                  <div className="font-semibold">{f.title}</div>
                  <div className="text-sm text-muted-foreground">{f.body}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <div
          className="flex items-center gap-3 text-sm text-faint"
          aria-hidden="true"
        >
          <ScoreRing score={42} size={28} />
          <ScoreRing score={71} size={28} />
          <ScoreRing score={88} size={28} />
          <span className="flex items-center gap-1.5">
            <CheckCheck className="size-4" /> Only true things leave the
            building.
          </span>
        </div>
      </aside>
      <main className="flex min-h-dvh items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <BrandMark />
            <span className="heading text-[1.2rem] font-bold">
              {DEFAULT_APP_NAME}
            </span>
          </div>
          {children}
        </div>
      </main>
    </div>
  )
}
