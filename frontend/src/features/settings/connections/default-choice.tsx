import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Chip } from "@/components/chip"
import { Button } from "@/components/ui/button"
import { putSetting, settingsKeys, settingsQuery } from "../api"
import type { Connection } from "./api"

const MAIL = ["gmail", "imap_smtp", "msgraph"]
const STORES = ["gdrive", "onedrive"]

/**
 * When more than one mailbox (or more than one cloud file store) is connected, say which one the app
 * uses first: the default mailbox sends and is the sending identity; the file store is where backups go.
 * Both are ordinary settings (`mail.default_mailbox`, `backups.target`), so the change is audited.
 */
export function DefaultChoice({
  c,
  all,
}: {
  c: Connection
  all: Connection[]
}) {
  const qc = useQueryClient()
  const settings = useQuery(settingsQuery())
  const kind = MAIL.includes(c.provider)
    ? "mail"
    : STORES.includes(c.provider)
      ? "store"
      : null
  const peers = all.filter(
    (x) => x.enabled && (kind === "mail" ? MAIL : STORES).includes(x.provider)
  )
  const key = kind === "mail" ? "mail.default_mailbox" : "backups.target"
  const save = useMutation({
    mutationFn: () => putSetting(key, kind === "mail" ? c.id : c.provider),
    onSuccess: () => qc.invalidateQueries({ queryKey: settingsKeys.all }),
  })
  if (!kind || peers.length < 2 || !settings.data) return null
  const current = settings.data
    .flatMap((g) => g.settings)
    .find((s) => s.key === key)?.value
  const oldest = [...peers].sort((a, b) =>
    a.created_at.localeCompare(b.created_at)
  )[0]
  const isDefault =
    kind === "mail"
      ? current
        ? current === c.id
        : oldest.id === c.id
      : current === c.provider
  if (isDefault)
    return (
      <Chip tone="good">
        {kind === "mail" ? "Default mailbox" : "Backups go here"}
      </Chip>
    )
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        onClick={() => save.mutate()}
        disabled={save.isPending}
        aria-label={
          kind === "mail"
            ? `Use ${c.label} as the default mailbox`
            : `Use ${c.label} for backups`
        }
      >
        {kind === "mail" ? "Use as default" : "Use for backups"}
      </Button>
      {save.isError && (
        <span role="alert" className="text-sm text-danger">
          {save.error.message}
        </span>
      )}
    </>
  )
}
