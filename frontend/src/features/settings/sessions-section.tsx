import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { useSignOut } from "@/features/auth/use-sign-out"
import type { Session } from "@/lib/api/types"
import {
  listSessions,
  revokeOtherSessions,
  revokeSession,
  sessionsKey,
} from "./api"

const when = (iso: string | null) =>
  iso
    ? new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(iso))
    : "not yet"

/** A plain name for a browser from its user agent ("Firefox on Windows"). */
export function deviceName(ua: string | null): string {
  if (!ua) return "Unknown device"
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /Firefox\//.test(ua)
      ? "Firefox"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Safari\//.test(ua)
          ? "Safari"
          : "A browser"
  const os = /Android/.test(ua)
    ? "Android"
    : /iPhone|iPad/.test(ua)
      ? "iOS"
      : /Windows/.test(ua)
        ? "Windows"
        : /Mac OS X/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : null
  return os ? `${browser} on ${os}` : browser
}

/** Where you are signed in, with sign-out per session and for every other one. */
export function SessionsSection() {
  const qc = useQueryClient()
  const signOut = useSignOut()
  const sessions = useQuery({ queryKey: sessionsKey, queryFn: listSessions })
  const refresh = () => qc.invalidateQueries({ queryKey: sessionsKey })
  const revoke = useMutation({
    mutationFn: (s: Session) => revokeSession(s.id),
    onSuccess: () => {
      toast.success("That session is signed out.")
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const others = useMutation({
    mutationFn: revokeOtherSessions,
    onSuccess: () => {
      toast.success("Every other session is signed out.")
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const list = sessions.data ?? []
  const hasOthers = list.some((s) => !s.current)

  return (
    <section aria-label="Sessions" className="panel p-4">
      <SectionHeader
        title="Sessions"
        action={
          hasOthers && (
            <Button
              variant="outline"
              size="sm"
              disabled={others.isPending}
              onClick={() => others.mutate()}
            >
              Sign out everywhere else
            </Button>
          )
        }
      />
      {sessions.isError ? (
        <p className="text-sm text-muted-foreground">
          The session list did not load. {sessions.error.message}
        </p>
      ) : (
        <ul className="grid gap-2" aria-label="Signed-in sessions">
          {list.map((s) => (
            <li
              key={s.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-sunken px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <b>{deviceName(s.user_agent)}</b>
                  {s.current && <Chip tone="good">This browser</Chip>}
                </div>
                <p className="text-sm text-muted-foreground">
                  Last active {when(s.last_seen_at)}
                  {s.ip ? ` from ${s.ip}` : ""}. Signed in {when(s.created_at)}.
                </p>
              </div>
              {s.current ? (
                <Button variant="outline" size="sm" onClick={() => signOut()}>
                  Sign out
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={revoke.isPending}
                  aria-label={`Sign out ${deviceName(s.user_agent)}`}
                  onClick={() => revoke.mutate(s)}
                >
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
