import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { KeyRound, PlugZap, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { Segmented } from "@/components/segmented"
import {
  aiKeys,
  connectionsQuery,
  createConnection,
  deleteConnection,
  LLM_PROVIDERS,
  money,
  testConnection,
  type Connection,
} from "./api"

type Provider = (typeof LLM_PROVIDERS)[number]
const PROVIDER_LABEL: Record<Provider, string> = {
  anthropic: "Anthropic API",
  openai_compatible: "OpenAI-compatible",
}

const healthTone = (h: Connection["health"]) =>
  h === "ok" ? "good" : h === "failing" ? "danger" : "neutral"

/** Provider records: keys are stored encrypted and only ever shown masked. */
export function ProvidersSection() {
  const queryClient = useQueryClient()
  const { data = [] } = useQuery(connectionsQuery())
  const providers = data.filter((c) =>
    (LLM_PROVIDERS as readonly string[]).includes(c.provider)
  )
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: aiKeys.connections })

  const test = useMutation({
    mutationFn: testConnection,
    onSuccess: (r) => {
      if (r.ok)
        toast.success(`Provider works. The test cost ${money(r.cost_minor)}.`)
      else toast.error(r.detail ?? "The test failed.")
      void refresh()
      void queryClient.invalidateQueries({ queryKey: aiKeys.spend })
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: deleteConnection,
    onSuccess: () => {
      toast.success("Provider removed.")
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })

  return (
    <section aria-labelledby="ai-providers" className="grid gap-3">
      <SectionHeader
        title={<span id="ai-providers">Providers</span>}
        aside="Keys are encrypted at rest and shown masked."
      />
      {providers.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No provider yet. Add an Anthropic API key, or an OpenAI-compatible
          endpoint (OpenRouter or your own model).
        </p>
      ) : (
        <ul className="grid gap-2" aria-label="Providers">
          {providers.map((c) => (
            <li
              key={c.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-md border border-border bg-surface row-pad"
            >
              <KeyRound className="size-4 text-faint" aria-hidden="true" />
              <span className="font-semibold">{c.label}</span>
              <Chip tone="line">
                {PROVIDER_LABEL[c.provider as Provider] ?? c.provider}
              </Chip>
              <span className="num text-sm text-muted-foreground">
                {c.secrets_masked.api_key ?? "no key"}
              </span>
              {typeof c.config.base_url === "string" && (
                <span className="text-sm text-faint">{c.config.base_url}</span>
              )}
              <Chip tone={healthTone(c.health)}>
                {c.health === "ok"
                  ? "Working"
                  : c.health === "failing"
                    ? "Failing"
                    : "Not tested"}
              </Chip>
              <span className="ml-auto flex gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={test.isPending}
                  onClick={() => test.mutate(c.id)}
                >
                  <PlugZap aria-hidden="true" />
                  Test
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Remove ${c.label}`}
                  onClick={() => remove.mutate(c.id)}
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <AddProvider onAdded={refresh} />
    </section>
  )
}

function AddProvider({ onAdded }: { onAdded: () => void }) {
  const [provider, setProvider] = useState<Provider>("anthropic")
  const [label, setLabel] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const add = useMutation({
    mutationFn: createConnection,
    onSuccess: () => {
      toast.success("Provider added. Test it before relying on it.")
      setLabel("")
      setApiKey("")
      setBaseUrl("")
      onAdded()
    },
    onError: (e) => toast.error(e.message),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate({
      provider,
      label: label.trim() || PROVIDER_LABEL[provider],
      config:
        provider === "openai_compatible" ? { base_url: baseUrl.trim() } : {},
      secrets: apiKey ? { api_key: apiKey } : {},
    })
  }
  return (
    <form
      onSubmit={submit}
      aria-label="Add a provider"
      className="grid gap-3 rounded-md border border-dashed border-border-strong p-3"
    >
      <Segmented<Provider>
        aria-label="Provider type"
        value={provider}
        onValueChange={setProvider}
        options={LLM_PROVIDERS.map((p) => ({
          value: p,
          label: PROVIDER_LABEL[p],
        }))}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor="provider-label">Name</Label>
          <Input
            id="provider-label"
            value={label}
            placeholder={PROVIDER_LABEL[provider]}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="provider-key">API key</Label>
          <Input
            id="provider-key"
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        {provider === "openai_compatible" && (
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="provider-url">Base URL</Label>
            <Input
              id="provider-url"
              type="url"
              required
              placeholder="https://openrouter.ai/api/v1"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
        )}
      </div>
      <div>
        <Button type="submit" disabled={add.isPending}>
          Add provider
        </Button>
      </div>
    </form>
  )
}
