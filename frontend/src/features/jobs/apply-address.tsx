import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, Mail, ShieldCheck } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { CHANNEL_LABEL } from "@/features/autopilot/logic"
import { studioKeys } from "@/features/studio/api"
import { explainError } from "@/lib/api/refusals"
import {
  jobKeys,
  setApplyEmail,
  type ApplyEmailIn,
  type ApplyEmailOut,
  type JobDetail,
} from "./api"
import { dateText } from "./format"

const FOUND_IN: Record<ApplyEmailOut["found_in"], string> = {
  posting_text: "Quoted in the posting",
  posting_link: "From the posting's email link",
  owner: "Set by you",
}

/** Whether an address may be emailed, in words: confirmed by the owner, a trusted domain, or not yet. */
export function addressStanding(e: ApplyEmailOut): {
  label: string
  tone: "good" | "warn"
} {
  if (e.confirmed)
    return {
      label: e.confirmed_at
        ? `Confirmed by you on ${dateText(e.confirmed_at)}`
        : "Confirmed by you",
      tone: "good",
    }
  if (e.trusted_domain) return { label: "Trusted domain", tone: "good" }
  return { label: "Not confirmed", tone: "warn" }
}

/**
 * Set, confirm or clear the role's application address. The returned JobDetail replaces the
 * job everywhere it is cached; a changed address can retire a packet, so those refresh too.
 */
export function useApplyEmail(
  jobId: string,
  onDone?: (job: JobDetail) => void
) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const m = useMutation({
    mutationFn: (body: ApplyEmailIn) => setApplyEmail(jobId, body),
    onMutate: () => setError(null),
    onSuccess: (job) => {
      qc.setQueryData(jobKeys.job(jobId), job)
      qc.setQueryData(studioKeys.job(jobId), job)
      void qc.invalidateQueries({ queryKey: ["autopilot"] })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      onDone?.(job)
    },
    onError: (e) => {
      const x = explainError(e, "Could not save the address.")
      setError(x.reason ? `${x.text} ${x.reason}` : x.text)
    },
  })
  return { ...m, error }
}

/** The job page's "How to apply": the address, where it came from, and each channel's standing. */
export function ApplyAddressPanel({ job }: { job: JobDetail }) {
  const e = job.apply_email
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState("")
  const save = useApplyEmail(job.id, () => setEditing(false))

  const startEdit = () => {
    setValue(e?.address ?? "")
    setEditing(true)
  }
  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    save.mutate(
      { address: value.trim(), confirmed: true },
      { onSuccess: () => toast.success("Address saved and confirmed.") }
    )
  }

  return (
    <div className="grid gap-3 panel p-4">
      <div
        className="grid gap-1.5"
        aria-label="Application address"
        role="group"
      >
        <div className="eyebrow">Application address</div>
        {e ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Mail aria-hidden="true" className="size-4 text-faint" />
              <span className="num font-medium" data-testid="apply-address">
                {e.address}
              </span>
              <AddressChip email={e} />
            </div>
            <p className="text-sm text-muted-foreground">
              {FOUND_IN[e.found_in]}
              {e.evidence && (
                <>
                  : <q>{e.evidence}</q>
                </>
              )}
            </p>
            {!e.usable && (
              <p className="text-sm text-muted-foreground">
                Nothing is emailed to an address you have not confirmed.
              </p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            The posting gives no application address.
          </p>
        )}
      </div>

      {editing ? (
        <form
          onSubmit={submit}
          aria-label="Correct the address"
          className="flex flex-wrap items-end gap-2"
        >
          <label className="grid gap-1 text-sm font-medium">
            Email address
            <Input
              inputMode="email"
              autoComplete="off"
              value={value}
              onChange={(x) => setValue(x.target.value)}
              placeholder="careers@example.com"
              className="w-72 max-w-full"
            />
          </label>
          <Button type="submit" disabled={save.isPending || !value.trim()}>
            Save and confirm
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setEditing(false)}
          >
            Cancel
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          {e && !e.confirmed && !e.trusted_domain && (
            <Button
              size="sm"
              disabled={save.isPending}
              onClick={() =>
                save.mutate(
                  {
                    confirmed: true,
                    address: e.found_in === "owner" ? e.address : null,
                  },
                  { onSuccess: () => toast.success("Address confirmed.") }
                )
              }
            >
              <CircleCheck aria-hidden="true" />
              Confirm this address
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={startEdit}>
            {e ? "Correct it" : "Add an address"}
          </Button>
          {e?.confirmed && (
            <Button
              size="sm"
              variant="ghost"
              disabled={save.isPending}
              onClick={() =>
                save.mutate({
                  address: e.found_in === "owner" ? e.address : null,
                  confirmed: false,
                })
              }
            >
              Withdraw confirmation
            </Button>
          )}
          {e?.found_in === "owner" && (
            <Button
              size="sm"
              variant="ghost"
              disabled={save.isPending}
              onClick={() =>
                save.mutate(
                  { address: null, confirmed: false },
                  {
                    onSuccess: () =>
                      toast.success("Back to the posting's address."),
                  }
                )
              }
            >
              Use the posting's address
            </Button>
          )}
        </div>
      )}
      {save.error && (
        <p role="alert" className="text-sm text-danger">
          {save.error}
        </p>
      )}

      {job.apply_channel_candidates.length > 0 && (
        <div className="grid gap-1.5 border-t border-border pt-3">
          <div className="eyebrow">Ways to apply</div>
          <ul className="grid gap-1.5" aria-label="Ways to apply">
            {job.apply_channel_candidates.map((c) => (
              <li
                key={c.channel}
                data-available={c.available}
                className="flex flex-wrap items-baseline gap-2 text-sm"
              >
                <span className="font-medium">{CHANNEL_LABEL[c.channel]}</span>
                <Chip tone={c.available ? "good" : "neutral"}>
                  {c.available ? "Available" : "Not available"}
                </Chip>
                <span className="text-muted-foreground">{c.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function AddressChip({ email }: { email: ApplyEmailOut }) {
  const s = addressStanding(email)
  return (
    <Chip
      tone={s.tone}
      icon={email.confirmed || email.trusted_domain ? ShieldCheck : undefined}
      data-testid="address-standing"
    >
      {s.label}
    </Chip>
  )
}

/**
 * A short notice where a packet is prepared or reviewed: the role's address is not confirmed,
 * with the sentence it came from and a Confirm action. Renders nothing when it is usable.
 */
export function ConfirmAddressNotice({
  job,
  note,
  onConfirmed,
}: {
  job: JobDetail | undefined
  /** What confirming changes here, e.g. "Prepare again to send it by email." */
  note?: string
  onConfirmed?: (job: JobDetail) => void
}) {
  const e = job?.apply_email
  const save = useApplyEmail(job?.id ?? "", onConfirmed)
  if (!job || !e || e.usable) return null
  return (
    <div
      role="group"
      aria-label="Unconfirmed application address"
      className="flex w-full flex-wrap items-center gap-2 rounded-sm bg-warn-soft px-3 py-2 text-sm text-warn"
    >
      <Mail aria-hidden="true" className="size-4 shrink-0" />
      <span className="min-w-0 flex-1">
        <b className="font-semibold">{e.address}</b> is not confirmed, so it is
        not emailed.
        {e.evidence && (
          <>
            {" "}
            {FOUND_IN[e.found_in]}: <q>{e.evidence}</q>
          </>
        )}
        {note && <> {note}</>}
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={save.isPending}
        onClick={() =>
          save.mutate(
            {
              confirmed: true,
              address: e.found_in === "owner" ? e.address : null,
            },
            { onSuccess: () => toast.success("Address confirmed.") }
          )
        }
      >
        Confirm the address
      </Button>
      {save.error && (
        <span role="alert" className="w-full text-danger">
          {save.error}
        </span>
      )}
    </div>
  )
}
