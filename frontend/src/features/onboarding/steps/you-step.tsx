import { useId, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useSave, type FactIn, type FactOut } from "@/features/kit/api"
import { personQuery, savePerson, type Person } from "../api"

type Form = {
  full_name: string
  preferred_name: string
  email: string
  location: string
  home_country: string
  timezone: string
  summary: string
}
const BLANK: Form = {
  full_name: "",
  preferred_name: "",
  email: "",
  location: "",
  home_country: "",
  timezone: "",
  summary: "",
}

const field = (value: string) =>
  value.trim()
    ? { value: value.trim(), visibility: "show_on_cv" as const }
    : null

/** Who you are, and one summary fact. Fields show what is already saved, never a made-up value. */
function fromPerson(p: Person | null | undefined): Form {
  if (!p) return BLANK
  return {
    ...BLANK,
    full_name: p.full_name.value,
    preferred_name: p.preferred_name?.value ?? "",
    email: p.email?.value ?? "",
    location: p.location?.value ?? "",
    home_country: p.home_country ?? "",
    timezone: p.timezone ?? "",
  }
}

/** Waits for what is saved, so the form opens showing it (never a made-up value). */
export function YouStep({ next }: { next: () => void }) {
  const person = useQuery(personQuery())
  if (person.isPending) return <p>Loading.</p>
  return <YouForm initial={person.data} next={next} />
}

function YouForm({
  initial,
  next,
}: {
  initial: Person | null | undefined
  next: () => void
}) {
  const qc = useQueryClient()
  const uid = useId()
  const addFact = useSave<FactOut, FactIn>("facts")
  const [f, setF] = useState<Form>(() => fromPerson(initial))

  const save = useMutation({
    mutationFn: async () => {
      await savePerson({
        full_name: { value: f.full_name.trim(), visibility: "show_on_cv" },
        preferred_name: field(f.preferred_name),
        email: field(f.email),
        location: field(f.location),
        home_country: f.home_country.trim() || null,
        timezone: f.timezone.trim() || null,
      })
      if (f.summary.trim())
        await addFact.mutateAsync({
          body: { kind: "summary", text: f.summary.trim() },
        })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kit"] })
      setF((cur) => ({ ...cur, summary: "" }))
      next()
    },
  })

  const set = (k: keyof Form) => (e: { target: { value: string } }) =>
    setF((cur) => ({ ...cur, [k]: e.target.value }))
  const row = (k: keyof Form, label: string, type = "text") => (
    <div className="grid gap-1">
      <label htmlFor={`${uid}-${k}`} className="font-semibold">
        {label}
      </label>
      <Input
        id={`${uid}-${k}`}
        type={type}
        value={f[k]}
        onChange={set(k)}
        autoComplete="off"
      />
    </div>
  )
  return (
    <form
      aria-label="About you"
      className="grid max-w-[520px] gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (f.full_name.trim()) save.mutate()
      }}
    >
      {row("full_name", "Full name")}
      {row("preferred_name", "Name you go by (optional)")}
      {row("email", "Email on applications (optional)", "email")}
      {row("location", "Where you live (optional)")}
      {row("home_country", "Home country (optional)")}
      {row("timezone", "Time zone (optional)")}
      <div className="grid gap-1">
        <label htmlFor={`${uid}-summary`} className="font-semibold">
          One true sentence about you (optional)
        </label>
        <Textarea
          id={`${uid}-summary`}
          rows={3}
          value={f.summary}
          onChange={set("summary")}
        />
        <p className="text-sm text-muted-foreground">
          It is saved as a draft fact. Nothing is used in an application until
          you approve it in Kit, Library.
        </p>
      </div>
      <div>
        <Button type="submit" disabled={!f.full_name.trim() || save.isPending}>
          Save and continue
        </Button>
      </div>
      {save.isError && (
        <p role="alert" className="text-sm text-danger">
          {save.error.message}
        </p>
      )}
    </form>
  )
}
