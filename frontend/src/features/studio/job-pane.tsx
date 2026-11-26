import {
  Check,
  CircleDashed,
  CircleHelp,
  CircleSlash,
  Minus,
} from "lucide-react"
import { Chip } from "@/components/chip"
import { FactTag } from "@/components/fact-tag"
import { cn } from "@/lib/utils"
import type { JobDetail } from "./api"
import type { FactIndex, Keyword, RequirementRow } from "./draft"

const STRENGTH = {
  strong: { label: "Strong", icon: Check, cls: "text-good" },
  partial: { label: "Partial", icon: CircleDashed, cls: "text-warn" },
  gap: { label: "Gap", icon: CircleSlash, cls: "text-danger" },
} as const

/** The posting side of the Studio: requirements with their evidence, and keyword coverage. */
export function JobPane({
  job,
  rows,
  keywords,
  index,
}: {
  job: JobDetail | undefined
  rows: RequirementRow[]
  keywords: Keyword[]
  index: FactIndex
}) {
  const covered = keywords.filter((k) => k.covered).length
  return (
    <aside aria-label="The job" className="grid content-start gap-5">
      <section aria-labelledby="reqs-title" className="grid gap-1">
        <h3 id="reqs-title" className="eyebrow">
          Posting requirements
        </h3>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {job
              ? "The posting lists no requirements."
              : "Loading the posting..."}
          </p>
        ) : (
          <ul className="m-0 grid list-none p-0">
            {rows.map((r, i) => {
              const s = r.match ? STRENGTH[r.match.strength] : null
              const Icon = s?.icon ?? CircleHelp
              const facts = (r.match?.evidence_fact_ids ?? []).flatMap((id) => {
                const f = index.get(id)
                return f ? [f] : []
              })
              return (
                <li
                  key={`${r.text}-${i}`}
                  className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 border-b border-border py-2 text-[0.88rem]"
                >
                  <Icon
                    aria-hidden="true"
                    className={cn("mt-0.5 size-4", s?.cls ?? "text-faint")}
                  />
                  <div className="grid min-w-0 gap-1">
                    <span>
                      {r.text}
                      <span className="sr-only">
                        : {s ? s.label : "not assessed"}
                      </span>
                      {r.kind === "preferred" && (
                        <span className="ml-1 text-xs text-faint">
                          preferred
                        </span>
                      )}
                    </span>
                    {facts.length > 0 ? (
                      <span className="flex flex-wrap gap-1">
                        {facts.map((f) => (
                          <FactTag
                            key={f.id}
                            code={f.code}
                            text={f.text}
                            status={
                              f.status as "approved" | "draft" | "retired"
                            }
                          />
                        ))}
                      </span>
                    ) : (
                      <small className="text-[0.78rem] text-faint">
                        {r.match
                          ? r.match.strength === "gap"
                            ? "No evidence in your Kit"
                            : "No fact cited"
                          : "Not assessed in this draft"}
                      </small>
                    )}
                    {r.match?.note && (
                      <small className="text-[0.78rem] text-muted-foreground">
                        {r.match.note}
                      </small>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>
      {keywords.length > 0 && (
        <section aria-labelledby="kw-title" className="grid gap-2">
          <h3 id="kw-title" className="eyebrow">
            Keywords ·{" "}
            <span className="num">
              {covered}/{keywords.length}
            </span>{" "}
            covered
          </h3>
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {keywords.map((k) => (
              <li key={k.word}>
                <Chip
                  tone={k.covered ? "good" : "line"}
                  icon={k.covered ? Check : Minus}
                >
                  {k.word}
                  <span className="sr-only">
                    {k.covered ? ", covered" : ", not covered"}
                  </span>
                </Chip>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  )
}
