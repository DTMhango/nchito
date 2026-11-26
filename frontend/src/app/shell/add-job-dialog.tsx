import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useMutation } from "@tanstack/react-query"
import { Link2, TextQuote } from "lucide-react"
import { useNavigate } from "@tanstack/react-router"
import { toast } from "sonner"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field"
import { Segmented } from "@/components/segmented"
import { captureJob } from "@/lib/api/endpoints"
import { isApiError } from "@/lib/api/client"

type Mode = "link" | "text"

const schema = z
  .object({ mode: z.enum(["link", "text"]), url: z.string(), text: z.string() })
  .superRefine((v, ctx) => {
    if (v.mode === "link") {
      if (!/^https?:\/\/\S+\.\S+/.test(v.url.trim()))
        ctx.addIssue({
          code: "custom",
          path: ["url"],
          message: "Paste the full link, starting with https://",
        })
    } else if (v.text.trim().length < 80) {
      ctx.addIssue({
        code: "custom",
        path: ["text"],
        message:
          "Paste the whole posting: title, employer and the description.",
      })
    }
  })
type Values = z.infer<typeof schema>

/**
 * Manual capture (DESIGN 6): paste a posting link or its text. It goes through the same
 * pipeline as a sweep and lands under Matches.
 */
export function AddJobDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>("link")
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { mode: "link", url: "", text: "" },
  })

  const m = useMutation({
    mutationFn: (v: Values) =>
      captureJob(
        v.mode === "link" ? { url: v.url.trim() } : { text: v.text.trim() }
      ),
    onSuccess: (r) => {
      // The capture endpoint queues the posting (normalise, dedupe, score) and returns its id.
      toast.success("Queued: reading the posting", {
        description: "It is scored and filed under Matches in about a minute.",
        action: {
          label: "Open",
          onClick: () =>
            void navigate({ to: "/jobs/$id", params: { id: r.id } }),
        },
      })
      form.reset({ mode, url: "", text: "" })
      onOpenChange(false)
    },
    onError: (e) => {
      if (isApiError(e, 404))
        toast.error(
          "Adding jobs by hand isn't available on this server."
        )
      else
        toast.error(
          e instanceof Error ? e.message : "Couldn't add that job. Try again."
        )
    },
  })

  const switchMode = (next: Mode) => {
    setMode(next)
    form.setValue("mode", next)
    form.clearErrors()
  }

  const errors = form.formState.errors
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">Add a job</DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            Paste a posting link or its text. It is read, scored and filed under
            Matches, like anything a sweep finds.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={form.handleSubmit((v) => m.mutate(v))}
          noValidate
        >
          <Segmented<Mode>
            aria-label="What are you pasting?"
            value={mode}
            onValueChange={switchMode}
            options={[
              { value: "link", label: "Link", icon: Link2 },
              { value: "text", label: "Posting text", icon: TextQuote },
            ]}
          />
          {mode === "link" ? (
            <Field data-invalid={!!errors.url || undefined}>
              <FieldLabel htmlFor="add-url" className="eyebrow">
                Posting link
              </FieldLabel>
              <Input
                id="add-url"
                type="url"
                inputMode="url"
                autoFocus
                placeholder="https://careers.example.com/jobs/1234"
                aria-invalid={!!errors.url || undefined}
                {...form.register("url")}
              />
              {errors.url ? (
                <FieldError>{errors.url.message}</FieldError>
              ) : (
                <FieldDescription>
                  Any job board, careers page or application portal.
                </FieldDescription>
              )}
            </Field>
          ) : (
            <Field data-invalid={!!errors.text || undefined}>
              <FieldLabel htmlFor="add-text" className="eyebrow">
                Posting text
              </FieldLabel>
              <Textarea
                id="add-text"
                rows={7}
                autoFocus
                aria-invalid={!!errors.text || undefined}
                {...form.register("text")}
              />
              {errors.text ? (
                <FieldError>{errors.text.message}</FieldError>
              ) : (
                <FieldDescription>
                  For postings that came by email or as a PDF.
                </FieldDescription>
              )}
            </Field>
          )}
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={m.isPending}>
              {m.isPending ? "Sending…" : "Read and score"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
