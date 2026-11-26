import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { CheckCircle2, FlaskConical, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Switch } from "@/components/ui/switch"
import {
  sourceKeys,
  testSource,
  toSourceInput,
  updateSource,
  type Source,
  type SourceTest,
} from "./api"
import {
  ConnectorFields,
  JobSpyNotInstalled,
  useSearchConnections,
  useSourceSettings,
} from "./connector-form"
import {
  buildConfig,
  CONNECTOR_INFO,
  draftFromConfig,
  isNewConnector,
  isNotInstalled,
  type Draft,
} from "./connectors"
import { HealthDot } from "./shared"
import { ACCESS_LABEL, ACTION_LABEL, ago, plainError } from "./words"

type ActionKey = keyof typeof ACTION_LABEL

const asList = (v: unknown): string =>
  Array.isArray(v) ? v.map(String).join(", ") : ""

/** Per-source settings: search settings, rate limit, permitted actions, and "Test now". */
export function SourceDrawer({
  source,
  onClose,
}: {
  source: Source | null
  onClose: () => void
}) {
  return (
    <Sheet open={source !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {source && (
          <DrawerBody key={source.id} source={source} onClose={onClose} />
        )}
      </SheetContent>
    </Sheet>
  )
}

function DrawerBody({
  source,
  onClose,
}: {
  source: Source
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [keywords, setKeywords] = useState(asList(source.config?.keywords))
  const [maxAge, setMaxAge] = useState(
    String(source.config?.max_age_days ?? "")
  )
  const [rpm, setRpm] = useState(
    String(source.rate_limit?.requests_per_minute ?? 30)
  )
  const [burst, setBurst] = useState(String(source.rate_limit?.burst ?? 5))
  const [actions, setActions] = useState<Set<ActionKey>>(
    new Set(source.permitted_actions ?? [])
  )
  const [enabled, setEnabled] = useState(source.enabled ?? true)
  const [result, setResult] = useState<SourceTest | null>(null)
  const kind = isNewConnector(source.connector) ? source.connector : null
  const [draft, setDraft] = useState<Draft | null>(() =>
    kind ? draftFromConfig(kind, source.config) : null
  )
  const [problem, setProblem] = useState<string | null>(null)
  const settings = useSourceSettings()
  const connections = useSearchConnections()

  const rpmN = Number(rpm)
  const burstN = Number(burst)
  const maxAgeN = maxAge.trim() === "" ? null : Number(maxAge)
  const invalid =
    !Number.isInteger(rpmN) ||
    rpmN < 1 ||
    !Number.isInteger(burstN) ||
    burstN < 1 ||
    (maxAgeN !== null && (!Number.isInteger(maxAgeN) || maxAgeN < 1))

  const save = useMutation({
    mutationFn: (built: Record<string, unknown> | null) => {
      const config: Record<string, unknown> = built ?? { ...source.config }
      if (built)
        return updateSource(source.id, {
          ...toSourceInput(source),
          config,
          rate_limit: { requests_per_minute: rpmN, burst: burstN },
          permitted_actions: [...actions],
          enabled,
        })
      const kw = keywords
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean)
      if (kw.length) config.keywords = kw
      else delete config.keywords
      if (maxAgeN !== null) config.max_age_days = maxAgeN
      else delete config.max_age_days
      return updateSource(source.id, {
        ...toSourceInput(source),
        config,
        rate_limit: { requests_per_minute: rpmN, burst: burstN },
        permitted_actions: [...actions],
        enabled,
      })
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: sourceKeys.sources })
      toast.success(`Saved ${source.name}`)
      onClose()
    },
    onError: (e) => setProblem(e.message),
  })

  const submit = () => {
    if (!kind || !draft) return save.mutate(null)
    const built = buildConfig(kind, draft, settings, connections, source.config)
    if (!built.ok) return setProblem(built.error)
    setProblem(null)
    save.mutate(built.config)
  }

  const test = useMutation({
    mutationFn: () => testSource(source.id),
    onSuccess: setResult,
    onError: (e) => toast.error(e.message),
  })

  const toggle = (a: ActionKey, on: boolean) =>
    setActions((cur) => {
      const n = new Set(cur)
      if (on) n.add(a)
      else n.delete(a)
      return n
    })

  return (
    <>
      <SheetHeader>
        <SheetTitle>{source.name}</SheetTitle>
        <SheetDescription>
          {ACCESS_LABEL[source.access]}
          {source.access_notes ? `. ${source.access_notes}` : ""}
        </SheetDescription>
      </SheetHeader>

      <div className="grid gap-5 px-4 pb-4">
        <section aria-label="Status" className="grid gap-1 text-sm">
          <HealthDot status={source.health.status} />
          <span className="text-muted-foreground">
            Last success: {ago(source.last_success_at)}
          </span>
          {source.health.last_error && (
            <span className="text-warn">
              {plainError(source.health.last_error)}
            </span>
          )}
        </section>

        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="src-enabled">Use this source in sweeps</Label>
          <Switch
            id="src-enabled"
            checked={enabled}
            onCheckedChange={setEnabled}
          />
        </div>

        {kind && draft ? (
          <section aria-label="Source settings" className="grid gap-3">
            <p className="text-sm text-muted-foreground">
              {CONNECTOR_INFO[kind].blurb}
            </p>
            <ConnectorFields kind={kind} draft={draft} onChange={setDraft} />
          </section>
        ) : (
          <fieldset className="grid gap-3">
            <legend className="mb-1 eyebrow">Search settings</legend>
            <div className="grid gap-1.5">
              <Label htmlFor="src-keywords">Keywords</Label>
              <Input
                id="src-keywords"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="actuarial, reinsurance"
              />
              <p className="text-xs text-muted-foreground">
                Comma separated. Leave empty to use each campaign's own search.
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="src-age">Ignore postings older than (days)</Label>
              <Input
                id="src-age"
                inputMode="numeric"
                value={maxAge}
                onChange={(e) => setMaxAge(e.target.value)}
                aria-invalid={maxAgeN !== null && !(maxAgeN >= 1)}
              />
            </div>
          </fieldset>
        )}

        <fieldset className="grid gap-3">
          <legend className="mb-1 eyebrow">Rate limit</legend>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="src-rpm">Requests per minute</Label>
              <Input
                id="src-rpm"
                inputMode="numeric"
                value={rpm}
                onChange={(e) => setRpm(e.target.value)}
                aria-invalid={!(rpmN >= 1)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="src-burst">Burst</Label>
              <Input
                id="src-burst"
                inputMode="numeric"
                value={burst}
                onChange={(e) => setBurst(e.target.value)}
                aria-invalid={!(burstN >= 1)}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Lower these if a site keeps asking us to slow down.
          </p>
        </fieldset>

        <fieldset className="grid gap-2.5">
          <legend className="mb-1 eyebrow">Permitted actions</legend>
          {(Object.keys(ACTION_LABEL) as ActionKey[]).map((a) => (
            <div key={a} className="flex items-start gap-2.5">
              <Checkbox
                id={`act-${a}`}
                checked={actions.has(a)}
                onCheckedChange={(c) => toggle(a, c === true)}
                className="mt-0.5"
              />
              <Label htmlFor={`act-${a}`} className="grid gap-0.5 font-normal">
                <span className="font-medium">{ACTION_LABEL[a].label}</span>
                <span className="text-xs text-muted-foreground">
                  {ACTION_LABEL[a].hint}
                </span>
              </Label>
            </div>
          ))}
        </fieldset>

        <section aria-label="Test" className="grid gap-2">
          <div>
            <Button
              type="button"
              variant="outline"
              onClick={() => test.mutate()}
              disabled={test.isPending}
            >
              <FlaskConical aria-hidden="true" />
              {test.isPending ? "Testing..." : "Test now"}
            </Button>
          </div>
          {result && (
            <div
              role="status"
              className="grid gap-1 rounded-md border border-border bg-sunken p-3 text-sm"
            >
              {result.ok ? (
                <>
                  <span className="inline-flex items-center gap-1.5 font-medium text-good">
                    <CheckCircle2 className="size-4" aria-hidden="true" />
                    Worked: found {result.sample_count} sample roles
                  </span>
                  <ul className="list-disc pl-5 text-muted-foreground">
                    {result.sample_titles.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </>
              ) : (
                <>
                  <span className="inline-flex items-center gap-1.5 font-medium text-danger">
                    <XCircle className="size-4" aria-hidden="true" />
                    The test failed
                  </span>
                  {isNotInstalled(result.error) ? (
                    <JobSpyNotInstalled />
                  ) : (
                    <span className="text-muted-foreground">
                      {plainError(result.error)}
                    </span>
                  )}
                </>
              )}
            </div>
          )}
        </section>
      </div>

      {problem && (
        <p role="alert" className="px-4 text-sm text-danger">
          {problem}
        </p>
      )}
      <SheetFooter>
        <Button onClick={submit} disabled={invalid || save.isPending}>
          {save.isPending ? "Saving..." : "Save settings"}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </SheetFooter>
    </>
  )
}
