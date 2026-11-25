import { ScoreRing } from "@/components/score-ring"
import { Chip } from "@/components/chip"
import { ThemeScope } from "@/themes/scope"
import type { Mode, Theme } from "@/themes/schema"

/** Illustrative, fictional rows for the miniature. Not data. */
const ROWS = [
  {
    score: 88,
    title: "Head of Data",
    sub: "Example Payments · Remote",
    action: "approve" as const,
  },
  {
    score: 79,
    title: "Exposure Manager",
    sub: "Sample Re · Lusaka",
    action: "sign-in" as const,
  },
]

/**
 * A miniature of the app drawn in a given theme (the mockup's gallery card). Rendered in a
 * ThemeScope so it shows that theme regardless of the one in use.
 */
export function ThemePreview({ theme, mode }: { theme: Theme; mode: Mode }) {
  return (
    <ThemeScope
      theme={theme}
      mode={mode}
      aria-hidden="true"
      className="grid aspect-[16/10] max-w-full grid-cols-[22%_1fr] overflow-hidden rounded-lg border border-border text-[9px] transition-transform"
    >
      <span className="grid content-start gap-[5px] border-r border-border px-[7px] py-[9px]">
        <i className="mb-1 block size-3.5 rounded-[4px] bg-primary" />
        <i className="block h-1.5 rounded-full bg-primary-soft" />
        <i className="block h-1.5 rounded-full bg-border" />
        <i className="block h-1.5 rounded-full bg-border" />
        <i className="block h-1.5 rounded-full bg-border" />
      </span>
      <span className="grid min-w-0 content-start gap-1.5 px-2.5 py-[9px]">
        <span className="block heading text-[13px]">Needs you</span>
        <span className="block rounded-sm border border-border bg-surface shadow-elev">
          {ROWS.map((r, i) => (
            <span
              key={r.title}
              className={
                i
                  ? "grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-1.5 border-t border-border px-1.5 py-[5px]"
                  : "grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-1.5 px-1.5 py-[5px]"
              }
            >
              <ScoreRing score={r.score} size={18} />
              <span className="min-w-0 truncate font-semibold">
                {r.title}
                <small className="block truncate font-normal text-muted-foreground">
                  {r.sub}
                </small>
              </span>
              {r.action === "approve" ? (
                <b className="rounded-[max(0px,calc(var(--t-radius-sm)-2px))] bg-primary px-1.5 py-0.5 font-semibold text-primary-foreground">
                  Approve
                </b>
              ) : (
                <span className="rounded-full bg-warn-soft px-[5px] text-[8px] text-warn">
                  Sign in
                </span>
              )}
            </span>
          ))}
        </span>
        <span className="flex gap-1">
          <Chip tone="good" className="px-1.5 py-px text-[8px]">
            Applied 2
          </Chip>
          <Chip tone="accent" className="px-1.5 py-px text-[8px]">
            12 new
          </Chip>
          <Chip tone="info" className="px-1.5 py-px text-[8px]">
            Interview Fri
          </Chip>
        </span>
      </span>
    </ThemeScope>
  )
}
