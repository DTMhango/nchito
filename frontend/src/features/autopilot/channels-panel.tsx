import { useQuery } from "@tanstack/react-query"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { currentTaskText } from "@/features/settings/runners/logic"
import { runnersQuery } from "./api"
import { CHANNEL_RULES, ENFORCEMENT } from "./logic"

const seen = (iso: string | null) =>
  iso
    ? `last seen ${new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`
    : "never seen"

/** What each channel actually enforces (DESIGN 18.1), said plainly, with runner status. */
export function ChannelsPanel() {
  const runners = useQuery(runnersQuery())
  return (
    <section aria-label="What each channel enforces" className="grid gap-3">
      <SectionHeader
        title="What each channel enforces"
        aside="Automatic does not mean the same thing on every channel."
      />
      <ul className="grid gap-2.5 lg:grid-cols-2">
        {CHANNEL_RULES.map((r) => (
          <li
            key={r.title}
            className="grid content-start gap-1.5 rounded-lg border border-border bg-surface p-3.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-md">{r.title}</h4>
              <Chip tone={ENFORCEMENT[r.enforcement].tone}>
                {ENFORCEMENT[r.enforcement].label}
              </Chip>
            </div>
            <p className="text-sm text-muted-foreground">{r.body}</p>
          </li>
        ))}
      </ul>
      <div className="grid gap-1.5">
        <h4 className="eyebrow">Runners</h4>
        {runners.data && runners.data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No runner is connected, so the browser agent cannot work yet.
          </p>
        )}
        <ul className="grid gap-1.5">
          {runners.data?.map((r) => (
            <li
              key={r.token_id}
              className="flex flex-wrap items-center gap-2 text-sm"
            >
              <Chip tone={r.online ? "good" : "neutral"}>
                {r.online ? "Online" : "Offline"}
              </Chip>
              <span className="font-medium">{r.name}</span>
              <span className="text-faint">
                {r.runner_kind === "pc" ? "your PC" : "server"} ·{" "}
                {seen(r.last_seen_at)}
              </span>
              {r.current_task_id && (
                <span className="text-muted-foreground">
                  {currentTaskText(r)}
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
