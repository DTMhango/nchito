/** Settings > Connections > Calendar: the subscription feed, its detail level and reminders, and Google Calendar. */
import { useEffect } from "react"
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { Copy, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Chip } from "@/components/chip"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { api, isApiError, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"
import { settingsQuery } from "../api"
import { SettingsBlock } from "../data/settings-block"
import { GOOGLE_NOT_SET_UP } from "./connect-form"
import { oauthStart, updateConnection } from "./api"

export const calendarKeys = { all: ["calendar"] as const }

export const calendarQuery = () =>
  queryOptions({
    queryKey: calendarKeys.all,
    queryFn: () => unwrap(api.GET("/api/calendar")),
  })

const SETTING_KEYS = [
  "calendar.detail_level",
  "calendar.reminder_offsets_minutes",
  "calendar.prep_nudge_minutes",
]

export function CalendarCard() {
  const qc = useQueryClient()
  const q = useQuery(calendarQuery())
  const settings = useQuery(settingsQuery())
  const refresh = () => qc.invalidateQueries({ queryKey: calendarKeys.all })

  // A saved setting changes what the feed and Google show: look at the server again.
  const settingsStamp = settings.dataUpdatedAt
  useEffect(() => {
    if (settingsStamp) void qc.invalidateQueries({ queryKey: calendarKeys.all })
  }, [settingsStamp, qc])

  const rotate = useMutation({
    mutationFn: () => unwrap(api.POST("/api/calendar/feed")),
    onSuccess: () => {
      toast.success("New subscription link made. The old one stopped working.")
      void refresh()
    },
  })
  const revoke = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/calendar/feed")),
    onSuccess: () => {
      toast.success("Subscription link revoked")
      void refresh()
    },
  })

  return (
    <section aria-labelledby="conn-calendar" className="grid gap-4 panel p-4">
      <div>
        <h3 id="conn-calendar" className="text-md">
          Calendar
        </h3>
        <p className="max-w-[70ch] text-muted-foreground">
          Your interviews as a calendar. Subscribe from any calendar app with a
          private link, or let the app write them to its own Google Calendar.
          Your private notes never leave the app.
        </p>
      </div>

      {q.isPending && <Skeleton className="h-24 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-danger">
          Could not load the calendar settings.
        </p>
      )}
      {q.isSuccess && (
        <>
          <div className="grid gap-2">
            <div className="eyebrow">Subscription link</div>
            {q.data.feed_url ? (
              <FeedUrl url={q.data.feed_url} />
            ) : (
              <p className="text-sm text-muted-foreground">
                No link yet. Make one to subscribe from another calendar app.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant={q.data.feed_url ? "outline" : "default"}
                disabled={rotate.isPending}
                onClick={() => rotate.mutate()}
              >
                <RefreshCw aria-hidden="true" />
                {q.data.feed_url ? "Rotate link" : "Make a link"}
              </Button>
              {q.data.feed_url && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate()}
                >
                  Revoke link
                </Button>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              Anyone with the link can see your interview times. Rotate it to
              replace it; the old one stops working at once. Each interview on
              the role page also has its own .ics file.
            </p>
          </div>

          <SettingsBlock keys={SETTING_KEYS} label="Calendar settings" />

          <GoogleCalendar
            google={q.data.google}
            onChanged={() => void refresh()}
          />
        </>
      )}
    </section>
  )
}

function FeedUrl({ url }: { url: string }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      toast.success("Link copied")
    } catch {
      toast.error("Could not copy. Select the link and copy it by hand.")
    }
  }
  return (
    <div className="flex gap-2">
      <Input
        readOnly
        aria-label="Subscription link"
        value={url}
        onFocus={(e) => e.currentTarget.select()}
      />
      <Button size="sm" variant="outline" onClick={() => void copy()}>
        <Copy aria-hidden="true" />
        Copy
      </Button>
    </div>
  )
}

type Google = Schemas["GoogleState"]

function GoogleCalendar({
  google,
  onChanged,
}: {
  google: Google
  onChanged: () => void
}) {
  const start = useMutation({
    mutationFn: () => oauthStart("gcalendar"),
    onSuccess: ({ authorize_url }) => {
      if (/^https:\/\//.test(authorize_url))
        window.location.assign(authorize_url)
    },
  })
  const toggle = useMutation({
    mutationFn: (on: boolean) =>
      updateConnection(google.connection_id!, { enabled: on }),
    onSuccess: (_c, on) => {
      toast.success(on ? "Google Calendar is on" : "Google Calendar is off")
      onChanged()
    },
  })
  return (
    <div className="grid gap-2 border-t border-border pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="eyebrow">Google Calendar</div>
        {google.connected ? (
          <Chip tone={google.enabled ? "good" : "line"}>
            {google.enabled ? "On" : "Connected, off"}
          </Chip>
        ) : (
          <Chip tone="line">Not connected</Chip>
        )}
      </div>
      <p className="max-w-[70ch] text-sm text-muted-foreground">
        It is off until you switch it on. It only writes to a calendar of its
        own and never reads your calendars. {google.reads_description}
      </p>
      {google.connected ? (
        <label className="flex items-center gap-2 text-sm">
          <Switch
            checked={toggle.isPending ? toggle.variables : google.enabled}
            disabled={toggle.isPending}
            onCheckedChange={(on) => {
              toggle.mutate(on)
            }}
            aria-label="Write interviews to Google Calendar"
          />
          Write interviews to Google Calendar
        </label>
      ) : (
        <div>
          <Button
            size="sm"
            disabled={start.isPending || !google.configured}
            onClick={() => start.mutate()}
          >
            Connect Google Calendar
          </Button>
        </div>
      )}
      {!google.configured && !google.connected && (
        <p className="text-sm text-muted-foreground">{GOOGLE_NOT_SET_UP}</p>
      )}
      {(start.isError || toggle.isError) && (
        <p role="alert" className="text-sm text-danger">
          {isApiError(start.error, 409)
            ? GOOGLE_NOT_SET_UP
            : (start.error ?? toggle.error)?.message}
        </p>
      )}
    </div>
  )
}
