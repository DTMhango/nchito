import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { addTrusted, apKeys, removeTrusted, trustedQuery } from "./api"
import { DOMAIN_PATTERN, normaliseDomain } from "./logic"

/** Sites the browser agent may submit to without asking first (DESIGN 18.1). */
export function TrustedSitesPanel() {
  const q = useQuery(trustedQuery())
  const qc = useQueryClient()
  const [domain, setDomain] = useState("")
  const [system, setSystem] = useState("")
  const [error, setError] = useState<string | null>(null)
  const refresh = () => void qc.invalidateQueries({ queryKey: apKeys.trusted })

  const add = useMutation({
    mutationFn: () =>
      addTrusted({
        domain: normaliseDomain(domain),
        system: system.trim() || null,
        note: null,
      }),
    onSuccess: () => {
      toast.success("Site trusted.")
      setDomain("")
      setSystem("")
      refresh()
    },
    onError: (e) => setError(e.message),
  })
  const remove = useMutation({
    mutationFn: removeTrusted,
    onSuccess: () => {
      toast.success("No longer trusted. The agent will ask first.")
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!DOMAIN_PATTERN.test(normaliseDomain(domain)))
      return setError("Enter a domain such as careers.example.com.")
    setError(null)
    add.mutate()
  }

  return (
    <section aria-label="Trusted sites" className="grid gap-3">
      <SectionHeader
        title="Trusted sites"
        aside="The browser agent asks you first on any site not listed here."
      />
      <form
        onSubmit={submit}
        aria-label="Trust a site"
        className="flex flex-wrap items-end gap-2"
      >
        <label className="grid gap-1 text-sm font-medium">
          Domain
          <Input
            value={domain}
            onChange={(e) => {
              setDomain(e.target.value)
              setError(null)
            }}
            placeholder="careers.example.com"
            className="w-64 max-w-full"
            aria-invalid={error ? true : undefined}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium">
          Application system (optional)
          <Input
            value={system}
            onChange={(e) => setSystem(e.target.value)}
            placeholder="Greenhouse"
            className="w-48 max-w-full"
          />
        </label>
        <Button type="submit" disabled={add.isPending}>
          Trust this site
        </Button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      {q.isSuccess && q.data.length === 0 && (
        <EmptyState
          title="No trusted sites"
          description="Until you trust a site, the agent asks before submitting there."
        />
      )}
      <ul className="grid gap-1.5">
        {q.data?.map((s) => (
          <li
            key={s.id}
            className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface px-3 py-2"
          >
            <span className="font-medium">{s.domain}</span>
            {s.system && (
              <span className="text-sm text-muted-foreground">{s.system}</span>
            )}
            {s.note && <span className="text-sm text-faint">{s.note}</span>}
            <Button
              size="icon-sm"
              variant="ghost"
              className="ml-auto"
              aria-label={`Stop trusting ${s.domain}`}
              onClick={() => remove.mutate(s.id)}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
