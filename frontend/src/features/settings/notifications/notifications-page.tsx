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
      <Block
        id="events"
        title="What notifies you"
        lead="Which events send a message, and how much a message says. Generic messages name no role or employer."
        keys={[
          "notifications.events",
          "notifications.detail_level",
          "notifications.lookback_hours",
        ]}
      />
      <Block
        id="quiet"
        title="Quiet hours"
        lead="Messages are held during these hours (your time zone) and sent when they end. Applications have their own quiet hours under Automation."
        keys={[
          "notifications.quiet_hours_enabled",
          "notifications.quiet_hours_start",
          "notifications.quiet_hours_end",
        ]}
      />
      <Block
        id="digest"
        title="Digest"
        lead="One summary instead of many messages."
        keys={[
          "notifications.digest",
          "notifications.digest_time",
          "notifications.digest_skip_empty",
          "notifications.digest_max_items",
        ]}
      />
      <Block
        id="wording"
        title="Wording"
        lead="Message titles. Use the fields named in each description."
        keys={[
          "notifications.needs_you_title",
          "notifications.alert_title",
          "notifications.digest_title",
        ]}
      />
      <Block
        id="delivery"
        title="Delivery"
        lead="How often a failed message is tried again before it is given up."
        keys={["notifications.retry_attempts", "notifications.retry_minutes"]}
      />
    </div>
  )
}

function Block({
  id,
  title,
  lead,
  keys,
}: {
  id: string
  title: string
  lead: string
  keys: string[]
}) {
  return (
    <section aria-labelledby={`${id}-h`} className="grid gap-3 panel p-4">
      <div>
        <h3 id={`${id}-h`} className="text-md">
          {title}
        </h3>
        <p className="text-muted-foreground">{lead}</p>
      </div>
      <SettingsBlock label={title} keys={keys} />
    </section>
  )
}
