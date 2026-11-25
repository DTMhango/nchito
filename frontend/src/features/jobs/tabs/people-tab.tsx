import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Pencil, Plus, Trash2, Users } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import {
  contactsQuery,
  createContact,
  deleteContact,
  jobKeys,
  updateContact,
  type ContactIn,
  type ContactOut,
  type JobDetail,
} from "../api"

type FormState = { name: string; role: string; email: string; link: string; notes: string }
const blank: FormState = { name: "", role: "", email: "", link: "", notes: "" }

export function PeopleTab({ job }: { job: JobDetail }) {
  const qc = useQueryClient()
  const q = useQuery(contactsQuery())
  const [editing, setEditing] = useState<ContactOut | "new" | null>(null)
  const people = (q.data ?? []).filter((c) => c.job_id === job.id)
  const done = () => {
    setEditing(null)
    void qc.invalidateQueries({ queryKey: jobKeys.contacts })
  }
  const remove = useMutation({
    mutationFn: (id: string) => deleteContact(id),
    onSuccess: () => {
      toast.success("Person removed")
      done()
    },
  })

  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-2">
        <p className="text-sm text-muted-foreground">
          Recruiter, hiring manager, interviewers. Added by you or picked up from emails.
        </p>
        <Button size="sm" className="ml-auto" onClick={() => setEditing("new")}>
          <Plus aria-hidden="true" />
          Add person
        </Button>
      </div>

      {editing && (
        <ContactForm
          key={editing === "new" ? "new" : editing.id}
          jobId={job.id}
          contact={editing === "new" ? null : editing}
          onDone={done}
          onCancel={() => setEditing(null)}
        />
      )}

      {q.isPending ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : people.length === 0 && !editing ? (
        <EmptyState
          icon={Users}
          title="No one added yet"
          description="Add the recruiter or hiring manager so their details are with the role."
        />
      ) : (
        <ul className="panel p-4">
          {people.map((c) => (
            <li key={c.id} className="flex flex-wrap items-start gap-3 border-t border-border row-pad first:border-t-0">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <b>{c.name}</b>
                  {c.role && <span className="text-sm text-muted-foreground">{c.role}</span>}
                  {c.origin !== "owner" && <Chip tone="info">From {c.origin}</Chip>}
                </div>
                <div className="text-sm">
                  {c.email && <a className="text-primary-ink underline" href={`mailto:${c.email}`}>{c.email}</a>}
                  {c.email && c.link && " · "}
                  {c.link && (
                    <a className="text-primary-ink underline" href={c.link} target="_blank" rel="noreferrer noopener">
                      Profile
                    </a>
                  )}
                </div>
                {c.notes && <p className="text-sm text-muted-foreground">{c.notes}</p>}
              </div>
              <Button size="icon-sm" variant="ghost" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)}>
                <Pencil aria-hidden="true" />
              </Button>
              <Button size="icon-sm" variant="ghost" aria-label={`Remove ${c.name}`} onClick={() => remove.mutate(c.id)}>
                <Trash2 aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ContactForm({
  jobId,
  contact,
  onDone,
  onCancel,
}: {
  jobId: string
  contact: ContactOut | null
  onDone: () => void
  onCancel: () => void
}) {
  const [f, setF] = useState<FormState>(
    contact
      ? {
          name: contact.name,
          role: contact.role ?? "",
          email: contact.email ?? "",
          link: contact.link ?? "",
          notes: contact.notes ?? "",
        }
      : blank
  )
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => {
      const body: ContactIn = {
        job_id: jobId,
        name: f.name.trim(),
        role: f.role.trim() || null,
        email: f.email.trim() || null,
        link: f.link.trim() || null,
        notes: f.notes.trim() || null,
      }
      return contact ? updateContact(contact.id, body) : createContact(body)
    },
    onSuccess: () => {
      toast.success(contact ? "Person updated" : "Person added")
      onDone()
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Could not save."),
  })
  const set = (k: keyof FormState) => (e: { target: { value: string } }) =>
    setF({ ...f, [k]: e.target.value })
  return (
    <form
      aria-label={contact ? "Edit person" : "Add person"}
      className="grid gap-3 panel p-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (!f.name.trim()) return setError("Enter a name.")
        setError(null)
        save.mutate()
      }}
    >
      <label className="grid gap-1 text-sm">
        Name
        <Input value={f.name} onChange={set("name")} />
      </label>
      <label className="grid gap-1 text-sm">
        Role
        <Input value={f.role} onChange={set("role")} placeholder="Recruiter, hiring manager" />
      </label>
      <label className="grid gap-1 text-sm">
        Email
        <Input type="email" value={f.email} onChange={set("email")} />
      </label>
      <label className="grid gap-1 text-sm">
        Link
        <Input value={f.link} onChange={set("link")} placeholder="https://" />
      </label>
      <label className="grid gap-1 text-sm sm:col-span-2">
        Notes
        <Textarea rows={2} value={f.notes} onChange={set("notes")} />
      </label>
      {error && (
        <p role="alert" className="text-sm text-danger sm:col-span-2">
          {error}
        </p>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" size="sm" disabled={save.isPending}>
          Save person
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
