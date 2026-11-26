import { useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowLeft, Crown, PauseCircle } from "lucide-react"
import { Chip } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import { StagePill } from "@/components/stage-pill"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { View } from "@/components/view"
import { employerQuery, type EmployerRole } from "./api"
import { EmployerChip } from "./employer-chip"
import {
  EndCooldownDialog,
  MergeEmployerDialog,
  SplitAliasButton,
} from "./employer-dialogs"
import { shortDate } from "./employers-page"
import { OverridesEditor } from "./overrides-editor"

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="grid gap-2">
      <h3 className="eyebrow">{title}</h3>
      {children}
    </section>
  )
}

function RoleLine({ r }: { r: EmployerRole }) {
  return (
    <li className="flex flex-wrap items-center gap-2 py-1 text-sm">
      <Link
        to="/jobs/$id"
        params={{ id: r.job_id }}
        search={{ tab: "overview" }}
        className="font-semibold hover:underline"
      >
        {r.title}
      </Link>
      {r.stage && <StagePill stage={r.stage as never} />}
      {r.conflict_state === "winner" && (
        <Chip tone="good" icon={Crown}>
          Winner
        </Chip>
      )}
      {r.conflict_state === "held" && (
        <Chip tone="warn" icon={PauseCircle}>
          Held
        </Chip>
      )}
      {r.score !== null && (
        <span className="num text-muted-foreground">score {r.score}</span>
      )}
      {r.conflict_note && (
        <span className="text-muted-foreground">{r.conflict_note}</span>
      )}
    </li>
  )
}

/** One employer: roles seen, conflict groups, history, the cooldown rule, overrides, merge and split. */
export function EmployerPage({ employerKey }: { employerKey: string }) {
  const navigate = useNavigate()
  const q = useQuery(employerQuery(employerKey))
  const [ending, setEnding] = useState(false)
  const [merging, setMerging] = useState(false)

  if (q.isError)
    return (
      <View>
        <Alert variant="destructive" role="alert">
          <AlertTitle>Couldn't load this employer</AlertTitle>
          <AlertDescription>{q.error.message}</AlertDescription>
        </Alert>
      </View>
    )
  if (!q.data) return <View>Loading employer…</View>

  const d = q.data
  const e = d.employer
  const cd = d.cooldown

  return (
    <View>
      <Link
        to="/employers"
        className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden="true" />
        All employers
      </Link>
      <PageHeader
        title={e.name}
        meta={
          <EmployerChip
            chip={{ state: e.state, text: e.state_text }}
            hide={[]}
          />
        }
        description={`${e.applications} applications, last applied ${shortDate(e.last_applied_at)}. ${e.roles_seen} roles seen.`}
        actions={
          <Button variant="outline" size="sm" onClick={() => setMerging(true)}>
            Merge into another…
          </Button>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="grid content-start gap-6">
          <Section title="Cooldown">
            {cd ? (
              <div className="grid gap-2 text-sm">
                <p>{cd.rule}</p>
                <p className="text-muted-foreground">
                  {cd.running ? "Ends" : "Ended"} {shortDate(cd.ends_on)}.
                  Length: {d.cooldown_days} days ({d.cooldown_days_source}).
                </p>
                {cd.running && (
                  <div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEnding(true)}
                    >
                      End cooldown early…
                    </Button>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No cooldown is running. After an application ends, or goes
                unanswered, a new one waits {d.cooldown_days} days (
                {d.cooldown_days_source}).
              </p>
            )}
            {d.cooldown_ended_early_at && (
              <p className="text-sm text-muted-foreground">
                Ended early on {shortDate(d.cooldown_ended_early_at)} by{" "}
                {d.cooldown_ended_early_by}: {d.cooldown_ended_early_reason}
              </p>
            )}
          </Section>

          <Section title="Roles seen">
            {d.roles.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No roles seen yet.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {d.roles.map((r) => (
                  <RoleLine key={r.job_id} r={r} />
                ))}
              </ul>
            )}
          </Section>

          {d.conflict_groups.length > 0 && (
            <Section title="Roles that compete">
              {d.conflict_groups.map((g, i) => (
                <div
                  key={g[0]?.job_id ?? i}
                  className="rounded-sm bg-sunken p-3"
                >
                  <p className="text-sm text-muted-foreground">
                    Only the winner goes ahead; the others are held until it
                    closes or you release them.
                  </p>
                  <ul>
                    {g.map((r) => (
                      <RoleLine key={r.job_id} r={r} />
                    ))}
                  </ul>
                </div>
              ))}
            </Section>
          )}

          <Section title="History">
            {d.history.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No applications yet.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {d.history.map((h) => (
                  <li
                    key={h.application_id}
                    className="flex flex-wrap items-center gap-2 py-1 text-sm"
                  >
                    <span className="font-semibold">{h.title}</span>
                    <StagePill stage={h.stage as never} />
                    <span className="text-muted-foreground">
                      applied {shortDate(h.applied_at)}
                      {h.ended_at ? `, ended ${shortDate(h.ended_at)}` : ""}
                    </span>
                    {!h.counts_toward_cooldown && (
                      <span className="text-faint">
                        not counted for the cooldown
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>

        <div className="grid content-start gap-6">
          <Section title="Overrides">
            <OverridesEditor
              key={JSON.stringify([e, d.notes])}
              detail={d}
              employerKey={employerKey}
            />
          </Section>
          {d.aliases.length > 0 && (
            <Section title="Merged names">
              <ul className="grid gap-1.5">
                {d.aliases.map((a) => (
                  <li key={a} className="flex items-center gap-2 text-sm">
                    <span>{a}</span>
                    <SplitAliasButton alias={a} />
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
      </div>

      <EndCooldownDialog
        key={ending ? "open" : "closed"}
        open={ending}
        employerKey={employerKey}
        name={e.name}
        endsOn={cd ? shortDate(cd.ends_on) : null}
        onOpenChange={setEnding}
      />
      <MergeEmployerDialog
        key={merging ? "open" : "closed-m"}
        open={merging}
        employerKey={employerKey}
        name={e.name}
        onOpenChange={setMerging}
        onMerged={(into) =>
          void navigate({
            to: "/employers/$key",
            params: { key: into.toLowerCase() },
          })
        }
      />
    </View>
  )
}
