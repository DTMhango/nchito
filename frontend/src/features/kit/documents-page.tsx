import { useRef, useState } from "react"
import { Download, Eye, FileText, Upload } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Chip } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import {
  useKitList,
  useRemove,
  useSave,
  useUploadDocument,
  vaultDownloadUrl,
  type VaultDocumentOut,
  type VaultDocumentUpdate,
} from "./api"
import {
  ConfirmButton,
  errorText,
  Field,
  ListEmpty,
  NativeSelect,
  NeedsReviewChip,
  QueryGate,
  ReviewActions,
  ReviewBanner,
  SearchBox,
  useReviewFor,
} from "./common"
import { DOC_TYPES, fmtBytes, fmtDate, SENSITIVITY } from "./labels"

type DocType = VaultDocumentOut["doc_type"]
type Sens = VaultDocumentOut["sensitivity"]

const SENS_TONE = {
  normal: "neutral",
  on_request: "warn",
  after_offer_only: "danger",
} as const

function UploadForm() {
  const upload = useUploadDocument()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState("")
  const [type, setType] = useState<DocType>("cv")
  const [sens, setSens] = useState<Sens>("normal")
  return (
    <form
      aria-label="Upload a document"
      className="mb-5 grid gap-3 rounded-lg border border-border bg-surface-2 p-3.5 sm:grid-cols-[1fr_1fr_auto]"
      onSubmit={(e) => {
        e.preventDefault()
        if (!file || !title.trim()) return
        upload.mutate(
          { file, title: title.trim(), doc_type: type, sensitivity: sens },
          {
            onSuccess: () => {
              toast.success("Document added to the vault.")
              setFile(null)
              setTitle("")
              if (input.current) input.current.value = ""
            },
            onError: (err) => toast.error(errorText(err)),
          }
        )
      }}
    >
      <Field label="File">
        {(id) => (
          <input
            ref={input}
            id={id}
            type="file"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null
              setFile(f)
              if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""))
            }}
            className="h-8 min-w-0 rounded-md border border-input bg-surface text-sm file:mr-2 file:h-full file:border-0 file:bg-sunken file:px-2.5 file:text-sm file:font-medium"
          />
        )}
      </Field>
      <Field label="Title">
        {(id) => (
          <Input
            id={id}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        )}
      </Field>
      <div className="row-span-2 flex items-end">
        <Button
          type="submit"
          disabled={!file || !title.trim() || upload.isPending}
        >
          <Upload aria-hidden="true" />
          {upload.isPending ? "Uploading" : "Upload"}
        </Button>
      </div>
      <Field label="Type">
        {(id) => (
          <NativeSelect
            id={id}
            value={type}
            onChange={(e) => setType(e.target.value as DocType)}
          >
            {Object.entries(DOC_TYPES).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </NativeSelect>
        )}
      </Field>
      <Field label="When may it be sent?" hint={SENSITIVITY[sens].hint}>
        {(id) => (
          <NativeSelect
            id={id}
            value={sens}
            onChange={(e) => setSens(e.target.value as Sens)}
          >
            {Object.entries(SENSITIVITY).map(([v, s]) => (
              <option key={v} value={v}>
                {s.label}
              </option>
            ))}
          </NativeSelect>
        )}
      </Field>
    </form>
  )
}

function Preview({
  doc,
  onClose,
}: {
  doc: VaultDocumentOut
  onClose: () => void
}) {
  const url = vaultDownloadUrl(doc.id)
  const image = doc.mime_type.startsWith("image/")
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{doc.title}</DialogTitle>
          <DialogDescription>
            {DOC_TYPES[doc.doc_type]}, {fmtBytes(doc.size_bytes)}
            {doc.has_text_layer
              ? ", text can be read"
              : ", scanned image with no text"}
          </DialogDescription>
        </DialogHeader>
        <div className="h-[60vh] overflow-hidden rounded-md border border-border bg-paper">
          {image ? (
            <img
              src={url}
              alt={doc.title}
              className="size-full object-contain"
            />
          ) : (
            <iframe
              title={`Preview of ${doc.title}`}
              src={url}
              className="size-full"
            />
          )}
        </div>
        <div>
          <Button asChild variant="outline" size="sm">
            <a href={url} download>
              <Download aria-hidden="true" />
              Download
            </a>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function DocRow({
  d,
  onPreview,
}: {
  d: VaultDocumentOut
  onPreview: (d: VaultDocumentOut) => void
}) {
  const save = useSave<VaultDocumentOut, VaultDocumentUpdate>("vault")
  const remove = useRemove("vault")
  const patch = (p: Partial<VaultDocumentUpdate>) =>
    save.mutate(
      {
        id: d.id,
        body: {
          title: d.title,
          doc_type: d.doc_type,
          sensitivity: d.sensitivity,
          ...p,
        },
      },
      { onError: (e) => toast.error(errorText(e)) }
    )
  return (
    <li
      data-testid={`doc-${d.title}`}
      className="grid gap-2 border-t border-border px-3 py-2.5 first:border-t-0 md:grid-cols-[minmax(0,1fr)_8rem_11rem_auto] md:items-center"
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <FileText
          aria-hidden="true"
          className="size-5 shrink-0 text-muted-foreground"
        />
        <div className="min-w-0">
          <input
            aria-label={`Title of ${d.title}`}
            defaultValue={d.title}
            onBlur={(e) => {
              const v = e.target.value.trim()
              if (v && v !== d.title) patch({ title: v })
            }}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
            className="w-full rounded-sm border border-transparent bg-transparent px-1 font-medium outline-none hover:border-border focus:border-input focus:bg-surface"
          />
          <div className="flex flex-wrap items-center gap-x-2 px-1 text-xs text-muted-foreground">
            <span>{d.mime_type.split("/")[1]?.toUpperCase()}</span>
            <span className="num">{fmtBytes(d.size_bytes)}</span>
            <span>Added {fmtDate(d.created_at)}</span>
            {!d.has_text_layer && <Chip tone="warn">No text layer</Chip>}
            {d.review_state === "needs_review" && <NeedsReviewChip />}
          </div>
        </div>
      </div>
      <NativeSelect
        aria-label={`Type of ${d.title}`}
        value={d.doc_type}
        onChange={(e) => patch({ doc_type: e.target.value as DocType })}
      >
        {Object.entries(DOC_TYPES).map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </NativeSelect>
      <NativeSelect
        aria-label={`Sensitivity of ${d.title}`}
        value={d.sensitivity}
        onChange={(e) => patch({ sensitivity: e.target.value as Sens })}
        className={
          SENS_TONE[d.sensitivity] === "danger" ? "border-danger" : undefined
        }
      >
        {Object.entries(SENSITIVITY).map(([v, s]) => (
          <option key={v} value={v}>
            {s.label}
          </option>
        ))}
      </NativeSelect>
      <div className="flex flex-wrap items-center gap-1">
        {d.review_state === "needs_review" && (
          <ReviewActions entity="vault_document" id={d.id} label={d.title} />
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onPreview(d)}
          aria-label={`Preview ${d.title}`}
        >
          <Eye aria-hidden="true" />
          Preview
        </Button>
        <ConfirmButton
          label=""
          confirmLabel="Sure?"
          onConfirm={() => remove.mutate(d.id)}
        />
      </div>
    </li>
  )
}

/** Kit, Documents (vault, DESIGN 9): upload, type, sensitivity, preview. */
export function DocumentsPage() {
  const docs = useKitList<VaultDocumentOut>("vault")
  const [search, setSearch] = useState("")
  const [reviewOnly, setReviewOnly] = useState(false)
  const [preview, setPreview] = useState<VaultDocumentOut | null>(null)
  const review = useReviewFor("documents")
  const q = search.trim().toLowerCase()
  return (
    <div>
      <PageHeader
        title="Documents"
        description="Certificates, transcripts, ID and references, each with a sensitivity that decides when it may be attached."
      />
      <ReviewBanner
        count={review.count}
        only={reviewOnly}
        onOnlyChange={setReviewOnly}
      />
      <UploadForm />
      <div className="mb-3">
        <SearchBox
          value={search}
          onChange={setSearch}
          label="Search documents"
          placeholder="Search documents"
        />
      </div>
      <QueryGate query={docs}>
        {(all) => {
          const rows = all.filter(
            (d) =>
              (!reviewOnly || d.review_state === "needs_review") &&
              (!q ||
                `${d.title} ${DOC_TYPES[d.doc_type]}`.toLowerCase().includes(q))
          )
          return rows.length === 0 ? (
            <ListEmpty>
              {all.length === 0
                ? "The vault is empty. Upload a degree, transcript or certificate, and choose when it may be sent."
                : "No documents match."}
            </ListEmpty>
          ) : (
            <ul
              aria-label="Documents"
              className="m-0 list-none overflow-hidden rounded-lg border border-border bg-surface p-0"
            >
              {rows.map((d) => (
                <DocRow key={d.id} d={d} onPreview={setPreview} />
              ))}
            </ul>
          )
        }}
      </QueryGate>
      {preview && <Preview doc={preview} onClose={() => setPreview(null)} />}
    </div>
  )
}
