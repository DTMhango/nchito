import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { History, RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { cn } from "@/lib/utils"
import {
  putSetting,
  settingHistory,
  settingsKeys,
  type SettingOut,
} from "./api"
import {
  displayValue,
  isChoiceList,
  parseDraft,
  sameValue,
  toDraft,
  type Draft,
} from "./setting-value"
import { REFERENCE_PICKERS } from "./reference-pickers"

const SELECT_CLASS =
  "h-8 w-full min-w-0 rounded-md border field-focus border-input bg-surface px-2 text-base text-foreground outline-none"

const NUMERIC_KINDS = ["int", "float", "money_minor"]

/** One registry setting, rendered from its metadata alone (no bespoke code per setting). */
export function SettingRow({ setting: s }: { setting: SettingOut }) {
  const qc = useQueryClient()
  const id = useId()
  const [draft, setDraft] = useState<Draft>(() => toDraft(s))
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const baseline = toDraft(s)
  const dirty = !sameValue(draft, baseline)

  const save = useMutation({
    mutationFn: (value: unknown) => putSetting(s.key, value),
    onSuccess: (next) => {
      setError(null)
      setDraft(toDraft(next))
      void qc.invalidateQueries({ queryKey: settingsKeys.all })
      void qc.invalidateQueries({ queryKey: settingsKeys.history(s.key) })
      toast.success(`${s.label} saved`)
    },
    onError: (e) =>
      setError(e instanceof Error ? e.message : "Could not save."),
  })

  const submit = () => {
    const parsed = parseDraft(s, draft)
    if (!parsed.ok) return setError(parsed.error)
    setError(null)
    save.mutate(parsed.value)
  }
  const reset = () => {
    setError(null)
    save.mutate(s.default)
  }

  const errId = `${id}-err`
  const common = {
    id,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errId : undefined,
  }

  let control
  const Picker = REFERENCE_PICKERS[s.key]
  if (Picker) {
    control = (
      <Picker
        {...common}
        className={SELECT_CLASS}
        value={String(draft)}
        nullable={s.nullable}
        onChange={setDraft}
      />
    )
  } else if (s.kind === "bool") {
    control = (
      <Switch
        {...common}
        checked={draft === true}
        onCheckedChange={(v) => setDraft(v)}
        aria-label={s.label}
      />
    )
  } else if (s.kind === "enum" && s.choices) {
    control = (
      <select
        {...common}
        className={SELECT_CLASS}
        value={String(draft)}
        onChange={(e) => setDraft(e.target.value)}
      >
        {s.nullable && <option value="">Not set</option>}
        {s.choices.map((c) => (
          <option key={c} value={c}>
            {c.replaceAll("_", " ")}
          </option>
        ))}
      </select>
    )
  } else if (isChoiceList(s)) {
    const picked = Array.isArray(draft) ? draft : []
    control = (
      <div role="group" aria-label={s.label} className="flex flex-wrap gap-3">
        {s.choices!.map((c) => (
          <label key={c} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={picked.includes(c)}
              onCheckedChange={(v) =>
                setDraft(v ? [...picked, c] : picked.filter((p) => p !== c))
              }
            />
            {c}
          </label>
        ))}
      </div>
    )
  } else if (s.kind === "list") {
    const lines = String(draft).split("\n").length
    control = (
      <div className="grid gap-1">
        <Textarea
          {...common}
          rows={Math.min(8, Math.max(3, lines))}
          className="min-h-0 text-sm"
          value={String(draft)}
          placeholder="Nothing listed"
          onChange={(e) => setDraft(e.target.value)}
        />
        <span className="text-xs text-faint">One per line</span>
      </div>
    )
  } else {
    const numeric = NUMERIC_KINDS.includes(s.kind)
    control = (
      <div className="flex items-center gap-2">
        <Input
          {...common}
          type={s.kind === "time" ? "time" : "text"}
          inputMode={numeric ? "decimal" : undefined}
          className={cn("max-w-[260px]", numeric && "num")}
          value={String(draft)}
          placeholder={s.nullable ? "Not set" : undefined}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && dirty && submit()}
        />
        {s.unit && (
          <span className="text-sm text-muted-foreground">{s.unit}</span>
        )}
      </div>
    )
  }

  return (
    <li className="grid gap-2 border-t border-border row-pad first:border-t-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] md:gap-6">
      <div className="min-w-0">
        <label htmlFor={id} className="font-semibold">
          {s.label}
        </label>
        <p className="text-sm [overflow-wrap:anywhere] text-muted-foreground">
          {s.description}
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-faint">
          Default: <span className="num">{displayValue(s, s.default)}</span>
          {!s.is_default && <Chip tone="primary">Changed</Chip>}
        </p>
      </div>
      <div className="grid min-w-0 content-start gap-2">
        {control}
        {error && (
          <p id={errId} role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            size="sm"
            disabled={!dirty || save.isPending}
            onClick={submit}
            aria-label={`Save ${s.label}`}
          >
            Save
          </Button>
          {dirty && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraft(baseline)
                setError(null)
              }}
            >
              Discard
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={s.is_default || save.isPending}
            onClick={reset}
            aria-label={`Reset ${s.label} to default`}
          >
            <RotateCcw aria-hidden="true" />
            Reset
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={showHistory}
            aria-label={`${s.label} history`}
            onClick={() => setShowHistory((v) => !v)}
          >
            <History aria-hidden="true" />
            History
          </Button>
        </div>
        {showHistory && <SettingHistory setting={s} />}
      </div>
    </li>
  )
}

function SettingHistory({ setting: s }: { setting: SettingOut }) {
  const q = useQuery({
    queryKey: settingsKeys.history(s.key),
    queryFn: () => settingHistory(s.key),
  })
  if (q.isPending)
    return <p className="text-sm text-muted-foreground">Loading history...</p>
  if (q.isError)
    return <p className="text-sm text-danger">Could not load the history.</p>
  if (q.data.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        Never changed. It has been at its default since the start.
      </p>
    )
  return (
    <ol
      aria-label={`${s.label} changes`}
      className="grid gap-1.5 rounded-sm bg-sunken p-3 text-sm"
    >
      {q.data.map((r) => (
        <li key={r.version}>
          <span className="num">v{r.version}</span>{" "}
          {displayValue(s, r.old_value)} to{" "}
          <b>{displayValue(s, r.new_value)}</b>
          <span className="block text-xs text-faint">
            {r.changed_by}, {new Date(r.changed_at).toLocaleString()}
            {r.reason ? `. ${r.reason}` : ""}
          </span>
        </li>
      ))}
    </ol>
  )
}
