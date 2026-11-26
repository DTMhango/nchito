import { useId } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { toast } from "sonner"
import { AlertTriangle, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  putSetting,
  settingsKeys,
  settingsQuery,
  type SettingOut,
} from "@/features/settings/api"
import {
  connectionsQuery,
  type Connection,
} from "@/features/settings/connections/api"
import {
  JOBSPY_ENABLED_KEY,
  JOBSPY_INSTALL,
  OVERRIDES,
  SEARCH_PROVIDER,
  SOURCES_GROUP,
  searchConnectionFor,
  settingKey,
  settingValueText,
  type Draft,
  type NewConnector,
} from "./connectors"

const SELECT =
  "h-8 w-full min-w-0 rounded-md border field-focus border-input bg-surface px-2 text-base text-foreground outline-none"

/** The `sources` settings group, flattened (empty while loading). */
export function useSourceSettings(): SettingOut[] {
  const q = useQuery(settingsQuery())
  return (q.data ?? [])
    .filter((g) => g.key === SOURCES_GROUP)
    .flatMap((g) => g.settings)
}

/** Every Search API connection (paused ones too, so a chosen one can be explained). */
export function useSearchConnections(): Connection[] {
  const q = useQuery(connectionsQuery())
  return (q.data ?? []).filter((c) => c.provider === SEARCH_PROVIDER)
}

/** Shown when the backend says JobSpy is not installed: what it means and what to do. */
export function JobSpyNotInstalled() {
  return (
    <div
      role="alert"
      className="grid gap-1.5 rounded-md border border-warn bg-warn-soft p-3 text-sm"
    >
      <span className="inline-flex items-center gap-1.5 font-medium text-warn">
        <AlertTriangle className="size-4" aria-hidden="true" />
        JobSpy is not installed on this server
      </span>
      <p>
        It is an optional extra. Whoever runs the server adds it to the app
        image with <code>{JOBSPY_INSTALL}</code>, then restarts the app and the
        worker. Your other sources keep working meanwhile.
      </p>
    </div>
  )
}

/** The global JobSpy switch: it is off by default, and sweeps skip JobSpy until it is on. */
function JobSpySwitch({ settings }: { settings: SettingOut[] }) {
  const qc = useQueryClient()
  const s = settings.find((x) => x.key === JOBSPY_ENABLED_KEY)
  const turnOn = useMutation({
    mutationFn: () =>
      putSetting(JOBSPY_ENABLED_KEY, true, "Turned on from the Sources screen"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: settingsKeys.all })
      toast.success("JobSpy is on")
    },
    onError: (e) => toast.error(e.message),
  })
  if (!s || s.value === true) return null
  return (
    <div
      role="status"
      className="grid gap-2 rounded-md border border-border bg-sunken p-3 text-sm"
    >
      <p>
        <b>JobSpy is switched off</b> for every source (setting "{s.label}").
        Sweeps skip it until it is on. {s.description}
      </p>
      <div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => turnOn.mutate()}
          disabled={turnOn.isPending}
        >
          Turn JobSpy on
        </Button>
      </div>
    </div>
  )
}

/** One per-source override, rendered from its registry definition. Blank means "use the setting". */
function OverrideField({
  setting,
  value,
  onChange,
}: {
  setting: SettingOut
  value: string | string[] | undefined
  onChange: (v: string | string[]) => void
}) {
  const id = useId()
  const hint = `Leave as is to use the setting (${settingValueText(setting)}).`
  if (setting.kind === "list" && setting.choices) {
    const picked = Array.isArray(value) ? value : []
    return (
      <fieldset className="grid gap-1.5">
        <legend className="mb-1 text-sm font-medium">{setting.label}</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {setting.choices.map((c) => (
            <label key={c} className="flex items-center gap-1.5 text-sm">
              <Checkbox
                checked={picked.includes(c)}
                onCheckedChange={(on) =>
                  onChange(
                    on === true ? [...picked, c] : picked.filter((x) => x !== c)
                  )
                }
              />
              {c.replaceAll("_", " ")}
            </label>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          None ticked: use the setting ({settingValueText(setting)}).
        </p>
      </fieldset>
    )
  }
  const text = typeof value === "string" ? value : ""
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>
        {setting.label}
        {setting.unit ? ` (${setting.unit})` : ""}
      </Label>
      {setting.kind === "bool" ? (
        <select
          id={id}
          className={SELECT}
          value={text}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">
            Use the setting ({settingValueText(setting)})
          </option>
          <option value="true">On for this source</option>
          <option value="false">Off for this source</option>
        </select>
      ) : (
        <Input
          id={id}
          inputMode={setting.kind === "string" ? undefined : "numeric"}
          value={text}
          placeholder={settingValueText(setting)}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      <p className="text-xs text-muted-foreground">
        {setting.kind === "bool" ? setting.description : hint}
      </p>
    </div>
  )
}

function CareersFields({
  draft,
  onChange,
}: {
  draft: Draft
  onChange: (d: Draft) => void
}) {
  const set = (i: number, patch: Partial<Draft["employers"][number]>) =>
    onChange({
      ...draft,
      employers: draft.employers.map((e, j) =>
        j === i ? { ...e, ...patch } : e
      ),
    })
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-sm font-medium">Careers pages</legend>
      <ul aria-label="Careers pages" className="grid gap-2">
        {draft.employers.map((e, i) => (
          <li key={i} className="grid gap-1.5 sm:grid-cols-[1fr_12rem_auto]">
            <Input
              aria-label={`Careers page link ${i + 1}`}
              value={e.url}
              placeholder="https://careers.example.com/jobs"
              onChange={(ev) => set(i, { url: ev.target.value })}
            />
            <Input
              aria-label={`Employer name ${i + 1}`}
              value={e.name}
              placeholder="Employer (optional)"
              onChange={(ev) => set(i, { name: ev.target.value })}
            />
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label={`Remove careers page ${i + 1}`}
              disabled={draft.employers.length === 1}
              onClick={() =>
                onChange({
                  ...draft,
                  employers: draft.employers.filter((_, j) => j !== i),
                })
              }
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
      <div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() =>
            onChange({
              ...draft,
              employers: [...draft.employers, { url: "", name: "" }],
            })
          }
        >
          <Plus aria-hidden="true" /> Add another page
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        A page on Greenhouse, Lever, Ashby, Workable or Workday is read through
        that board, so the same role is not counted twice.
      </p>
    </fieldset>
  )
}

function SearchFields({
  draft,
  onChange,
  connections,
}: {
  draft: Draft
  onChange: (d: Draft) => void
  connections: Connection[]
}) {
  const id = useId()
  const used = searchConnectionFor(draft.connectionId, connections)
  const enabled = connections.filter((c) => c.enabled)
  if (connections.length === 0)
    return (
      <div
        role="alert"
        className="grid gap-1 rounded-md bg-warn-soft p-3 text-sm"
      >
        <b>No Search API connection yet.</b>
        <span>
          Web search needs a search provider's key.{" "}
          <Link to="/settings/connections" className="underline">
            Add a Search API connection
          </Link>{" "}
          first, then come back.
        </span>
      </div>
    )
  const first = searchConnectionFor("", connections)
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>Search API connection</Label>
      <select
        id={id}
        className={SELECT}
        value={draft.connectionId}
        onChange={(e) => onChange({ ...draft, connectionId: e.target.value })}
      >
        <option value="">
          {first
            ? `The first one that is on (now ${first.label})`
            : "The first one that is on (none is on)"}
        </option>
        {connections.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
            {c.enabled ? "" : " (paused)"}
          </option>
        ))}
      </select>
      {used ? (
        <p className="text-xs text-muted-foreground">
          Searches go to <code>{String(used.config.endpoint ?? "")}</code>. The
          address, the answer's shape and the key are set on the connection
          (Settings, Connections), never on the source.
        </p>
      ) : (
        <p role="alert" className="text-xs text-danger">
          {enabled.length === 0
            ? "Every Search API connection is paused. Turn one on in Settings, Connections."
            : "That connection is paused. Choose another."}
        </p>
      )}
    </div>
  )
}

/** The connector-specific part of the add dialog and the source drawer. */
export function ConnectorFields({
  kind,
  draft,
  onChange,
}: {
  kind: NewConnector
  draft: Draft
  onChange: (d: Draft) => void
}) {
  const settings = useSourceSettings()
  const connections = useSearchConnections()
  const queriesId = useId()
  const setOverride = (name: string, v: string | string[]) =>
    onChange({ ...draft, overrides: { ...draft.overrides, [name]: v } })
  const overrides = OVERRIDES[kind]
    .map((name) => ({
      name,
      setting: settings.find((s) => s.key === settingKey(kind, name)),
    }))
    .filter((o): o is { name: string; setting: SettingOut } => !!o.setting)

  return (
    <div className="grid gap-4">
      {kind === "jobspy" && <JobSpySwitch settings={settings} />}
      {kind === "careers_page" && (
        <CareersFields draft={draft} onChange={onChange} />
      )}
      {kind === "web_search" && (
        <SearchFields
          draft={draft}
          onChange={onChange}
          connections={connections}
        />
      )}
      {kind === "jobspy" && (
        <div className="grid gap-1.5">
          <Label htmlFor={queriesId}>Search phrases (optional)</Label>
          <Textarea
            id={queriesId}
            rows={3}
            value={draft.queries}
            onChange={(e) => onChange({ ...draft, queries: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">
            One per line. Leave empty to search each campaign's own titles.
          </p>
        </div>
      )}
      {overrides.length > 0 && (
        <fieldset className="grid gap-3">
          <legend className="mb-1 eyebrow">For this source only</legend>
          <p className="text-xs text-muted-foreground">
            Each value below follows the Discovery settings unless you change it
            here.
          </p>
          {overrides.map(({ name, setting }) => (
            <OverrideField
              key={name}
              setting={setting}
              value={draft.overrides[name]}
              onChange={(v) => setOverride(name, v)}
            />
          ))}
        </fieldset>
      )}
    </div>
  )
}
