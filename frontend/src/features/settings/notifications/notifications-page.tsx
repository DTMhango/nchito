import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { PageHeader } from "@/components/page-header"
import { Chip } from "@/components/chip"
import { settingsQuery } from "../api"
import { connectionsQuery } from "../connections/api"
import { SettingsBlock } from "../data/settings-block"

/** The notification channels and the connection that carries each one. */
const CHANNELS = [
  { id: "telegram", label: "Telegram", providers: ["telegram"] },
  { id: "email", label: "Email", providers: ["gmail", "imap_smtp"] },
  { id: "webhook", label: "Webhook", providers: ["webhook"] },
] as const

export function NotificationsPage() {
  const conns = useQuery(connectionsQuery())
  const settings = useQuery(settingsQuery())
  const chosen = (settings.data ?? [])
    .flatMap((g) => g.settings)
    .find((s) => s.key === "notifications.channels")?.value
  const chosenIds = Array.isArray(chosen) ? (chosen as string[]) : []
  const ready = (providers: readonly string[]) =>
    (conns.data ?? []).some(
      (c) =>
        providers.includes(c.provider) && c.enabled && c.health !== "failing"
    )
  const broken = CHANNELS.filter(
    (c) => chosenIds.includes(c.id) && conns.isSuccess && !ready(c.providers)
  )

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Notifications"
        description="What reaches you, where, and when. Nothing goes out until a channel is connected."
      />
      <section aria-labelledby="chan-h" className="grid gap-3 panel p-4">
        <h3 id="chan-h" className="text-md">
          Channels
        </h3>
        <ul aria-label="Channel status" className="grid gap-1.5">
          {CHANNELS.map((c) => {
            const ok = conns.isSuccess && ready(c.providers)
            return (
              <li key={c.id} className="flex flex-wrap items-center gap-2">
                <span className="w-24 font-medium">{c.label}</span>
                <Chip tone={ok ? "good" : "neutral"}>
                  {ok ? "Connected" : "Not connected"}
                </Chip>
                {chosenIds.includes(c.id) && <Chip tone="primary">In use</Chip>}
              </li>
            )
          })}
        </ul>
        {broken.length > 0 && (
          <p
            role="alert"
            className="rounded-sm bg-warn-soft px-3 py-2 text-warn"
          >
            {broken.map((b) => b.label).join(" and ")}{" "}
            {broken.length === 1 ? "is" : "are"} chosen but not connected, so
            nothing is sent there.{" "}
            <Link to="/settings/connections" className="underline">
              Connect it
            </Link>
          </p>
        )}
        <SettingsBlock
          label="Where notifications go"
          keys={["notifications.channels"]}
        />
      </section>
      <section aria-labelledby="digest-h" className="grid gap-3 panel p-4">
        <h3 id="digest-h" className="text-md">
          Daily digest
        </h3>
        <SettingsBlock label="Digest" keys={["notifications.digest"]} />
      </section>
      <section aria-labelledby="quiet-h" className="grid gap-3 panel p-4">
        <div>
          <h3 id="quiet-h" className="text-md">
            Quiet hours
          </h3>
          <p className="text-muted-foreground">
            Applications are not sent during these hours (your time zone). This
            is the same setting as under Automation.
          </p>
        </div>
        <SettingsBlock
          label="Quiet hours"
          keys={["automation.quiet_hours_start", "automation.quiet_hours_end"]}
        />
      </section>
    </div>
  )
}
