import { useState } from "react"
import { LayoutTemplate, Lock, Pencil, PenLine } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { PageHeader, SectionHeader } from "@/components/page-header"
import { useKitList, useSave, type TemplateOut } from "./api"
import {
  Field,
  FormDialog,
  ListEmpty,
  NeedsReviewChip,
  QueryGate,
  ReviewActions,
  ReviewBanner,
  SearchBox,
  useReviewFor,
} from "./common"
import { csv, parseCsv } from "./labels"

const KIND = { cv: "CV", letter: "Letter", email: "Email" } as const

const toBody = (t: TemplateOut, p: Record<string, unknown> = {}) => ({
  key: t.key,
  kind: t.kind,
  name: t.name,
  html: t.html,
  css: t.css,
  section_order: t.section_order,
  limits: t.limits,
  accent: t.accent,
  ...p,
})

const limitText = (t: TemplateOut) =>
  [
    t.limits?.pages
      ? `${t.limits.pages} page${t.limits.pages === 1 ? "" : "s"}`
      : null,
    t.limits?.paragraphs ? `${t.limits.paragraphs} paragraphs` : null,
    t.limits?.bullets_per_role
      ? `${t.limits.bullets_per_role} bullets per role`
      : null,
  ]
    .filter(Boolean)
    .join(", ") || "No limits set"

function TemplateDialog({
  t,
  onClose,
}: {
  t: TemplateOut
  onClose: () => void
}) {
  const save = useSave<TemplateOut, ReturnType<typeof toBody>>("templates")
  const [name, setName] = useState(t.name)
  const [order, setOrder] = useState(csv(t.section_order))
  const [pages, setPages] = useState(t.limits?.pages?.toString() ?? "")
  const [paragraphs, setParagraphs] = useState(
    t.limits?.paragraphs?.toString() ?? ""
  )
  const [bullets, setBullets] = useState(
    t.limits?.bullets_per_role?.toString() ?? ""
  )
  const n = (s: string) => (s.trim() ? Math.max(1, Number(s)) : null)
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Edit ${t.name}`}
      description="Name, section order and limits. The layout itself is edited in the template editor, which arrives with document rendering."
      saving={save.isPending}
      error={save.error}
      onSubmit={() =>
        save.mutate(
          {
            id: t.id,
            body: toBody(t, {
              name: name.trim() || t.name,
              section_order: parseCsv(order),
              limits: {
                pages: n(pages),
                paragraphs: n(paragraphs),
                bullets_per_role: n(bullets),
              },
            }),
          },
          {
            onSuccess: () => {
              toast.success("Template saved.")
              onClose()
            },
          }
        )
      }
    >
      <Field label="Name">
        {(id) => (
          <Input
            id={id}
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}
      </Field>
      <Field
        label="Section order"
        hint="Separate with commas, first section on top."
      >
        {(id) => (
          <Input
            id={id}
            value={order}
            onChange={(e) => setOrder(e.target.value)}
          />
        )}
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Most pages">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={1}
              value={pages}
              onChange={(e) => setPages(e.target.value)}
            />
          )}
        </Field>
        <Field label="Most paragraphs">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={1}
              value={paragraphs}
              onChange={(e) => setParagraphs(e.target.value)}
            />
          )}
        </Field>
        <Field label="Most bullets per role">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={1}
              value={bullets}
              onChange={(e) => setBullets(e.target.value)}
            />
          )}
        </Field>
      </div>
    </FormDialog>
  )
}

/** Kit, Templates (DESIGN 9): list and metadata. Rendering and the editor arrive in wave 2. */
export function TemplatesPage() {
  const templates = useKitList<TemplateOut>("templates")
  const [search, setSearch] = useState("")
  const [reviewOnly, setReviewOnly] = useState(false)
  const [editing, setEditing] = useState<TemplateOut | null>(null)
  const review = useReviewFor("templates")
  const q = search.trim().toLowerCase()
  return (
    <div>
      <PageHeader
        title="Templates"
        description="CV, letter and email layouts with their limits. Three CV templates ship: Classic, Compact and Modern, all single-column and text-extractable."
      />
      <ReviewBanner
        count={review.count}
        only={reviewOnly}
        onOnlyChange={setReviewOnly}
      />
      <div className="mb-4">
        <SearchBox
          value={search}
          onChange={setSearch}
          label="Search templates"
          placeholder="Search templates"
        />
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <QueryGate query={templates}>
          {(all) => {
            const rows = all.filter(
              (t) =>
                (!reviewOnly || t.review_state === "needs_review") &&
                (!q ||
                  `${t.name} ${t.key} ${KIND[t.kind]}`
                    .toLowerCase()
                    .includes(q))
            )
            return rows.length === 0 ? (
              <ListEmpty>
                {all.length === 0 ? "No templates yet." : "No templates match."}
              </ListEmpty>
            ) : (
              <ul
                aria-label="Templates"
                className="m-0 list-none self-start overflow-hidden rounded-lg border border-border bg-surface p-0"
              >
                {rows.map((t) => (
                  <li
                    key={t.id}
                    data-testid={`template-${t.key}`}
                    className="grid gap-1.5 border-t border-border px-3 py-3 first:border-t-0"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <LayoutTemplate
                        aria-hidden="true"
                        className="size-4 text-muted-foreground"
                      />
                      <h3 className="text-base font-semibold">{t.name}</h3>
                      <Chip tone="neutral">{KIND[t.kind]}</Chip>
                      {t.builtin && (
                        <Chip tone="line" icon={Lock}>
                          Built in
                        </Chip>
                      )}
                      {t.review_state === "needs_review" && <NeedsReviewChip />}
                      <span className="ml-auto flex items-center gap-1">
                        {t.review_state === "needs_review" && (
                          <ReviewActions
                            entity="template"
                            id={t.id}
                            label={t.name}
                            onEdit={() => setEditing(t)}
                          />
                        )}
                        {!t.builtin && (
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={`Edit ${t.name}`}
                            onClick={() => setEditing(t)}
                          >
                            <Pencil aria-hidden="true" />
                            Edit
                          </Button>
                        )}
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {limitText(t)}
                    </p>
                    {(t.section_order ?? []).length > 0 && (
                      <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0 text-sm">
                        {(t.section_order ?? []).map((s, i) => (
                          <li
                            key={s}
                            className="inline-flex items-center gap-1"
                          >
                            {i > 0 && (
                              <span aria-hidden="true" className="text-faint">
                                /
                              </span>
                            )}
                            <span className="capitalize">{s}</span>
                          </li>
                        ))}
                      </ol>
                    )}
                  </li>
                ))}
              </ul>
            )
          }}
        </QueryGate>
        <aside aria-label="Template editor">
          <SectionHeader
            as="h3"
            title="Template editor"
            aside="Coming with document rendering"
          />
          <div className="rounded-lg border border-dashed border-border-strong bg-surface-2 p-4">
            <div
              className="mb-4 grid grid-cols-[2fr_1fr] gap-3"
              aria-hidden="true"
            >
              <div className="grid gap-2 rounded-md bg-paper p-3">
                <div className="h-3 w-1/2 rounded-sm bg-sunken" />
                <div className="h-2 w-full rounded-sm bg-sunken" />
                <div className="h-2 w-5/6 rounded-sm bg-sunken" />
                <div className="mt-2 h-3 w-1/3 rounded-sm bg-sunken" />
                <div className="h-2 w-full rounded-sm bg-sunken" />
                <div className="h-2 w-2/3 rounded-sm bg-sunken" />
              </div>
              <div className="grid content-start gap-2">
                <div className="h-6 rounded-sm bg-sunken" />
                <div className="h-6 rounded-sm bg-sunken" />
                <div className="h-6 rounded-sm bg-sunken" />
              </div>
            </div>
            <EmptyState
              icon={PenLine}
              title="Layouts are edited here soon"
              description="You will drag sections, set the accent and see the page as a PDF and Word file. For now you can change a template's name, section order and limits."
              className="py-2"
            />
          </div>
        </aside>
      </div>
      {editing && (
        <TemplateDialog
          key={editing.id}
          t={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
