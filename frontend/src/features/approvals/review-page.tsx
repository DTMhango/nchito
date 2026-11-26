import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import {
  ArrowLeft,
  CircleCheck,
  FileText,
  Globe,
  Mail,
  OctagonAlert,
  ShieldCheck,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { View } from "@/components/view"
import { appKeys, getApplication } from "@/features/applications/api"
import { jobQuery } from "@/features/jobs/api"
import { ConfirmAddressNotice } from "@/features/jobs/apply-address"
import { preparePacket } from "@/features/studio/api"
import { meQuery } from "@/lib/api/endpoints"
import { explainCode, explainError, type Explained } from "@/lib/api/refusals"
import { isApiError } from "@/lib/api/client"
import {
  apKeys,
  approvePacket,
  createDispatch,
  currentPacketQuery,
  heldRolesQuery,
  packetsQuery,
  receiptQuery,
  rejectApplication,
  requestChanges,
  type Channel,
  type PacketContents,
} from "@/features/autopilot/api"
import {
  approvalStanding,
  CHANNEL_LABEL,
  deferredText,
  shortHash,
  stamp,
} from "@/features/autopilot/logic"
import { GateList } from "./gate-list"
import { HandoffPanel } from "./handoff-panel"

/** What stopped an action, in plain words (switched on `code`), with the server's reason and gates. */
type Problem = Explained

const problemOf = (e: unknown): Problem =>
  explainError(e, "Something went wrong. Try again in a moment.")
const plain = (message: string): Problem => ({
  code: "error",
  text: message,
  action: null,
  reason: null,
  gates: [],
})

/** Packet review: exactly what will be sent, why it can or cannot go automatically, and the decision. */
export function ReviewPage({ applicationId }: { applicationId: string }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const app = useQuery({
    queryKey: appKeys.detail(applicationId),
    queryFn: () => getApplication(applicationId),
  })
  const current = useQuery(currentPacketQuery(applicationId))
  const hasPacket = current.isSuccess && current.data !== null
  const receipt = useQuery({
    ...receiptQuery(applicationId),
    enabled: hasPacket,
  })
  const packets = useQuery(packetsQuery(applicationId))
  const held = useQuery(heldRolesQuery())
  const tz = useQuery(meQuery()).data?.timezone
  const [mode, setMode] = useState<"changes" | "reject" | null>(null)
  const [note, setNote] = useState("")
  const [problem, setProblem] = useState<Problem | null>(null)
  const [addressConfirmed, setAddressConfirmed] = useState(false)
  const job = useQuery({
    ...jobQuery(app.data?.job_id ?? ""),
    enabled: !!app.data,
  })
  const setError = (message: string | null) =>
    setProblem(message ? plain(message) : null)

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: apKeys.packet(applicationId) })
    void qc.invalidateQueries({ queryKey: apKeys.receipt(applicationId) })
    void qc.invalidateQueries({ queryKey: apKeys.packets(applicationId) })
    void qc.invalidateQueries({ queryKey: apKeys.dispatches(applicationId) })
    void qc.invalidateQueries({ queryKey: apKeys.queue })
    void qc.invalidateQueries({ queryKey: ["applications"] })
    void qc.invalidateQueries({ queryKey: ["pending-actions"] })
    void qc.invalidateQueries({ queryKey: ["today"] })
  }

  const channel: Channel = app.data?.channel ?? "manual"
  const approve = useMutation({
    mutationFn: () =>
      approvePacket(applicationId, receipt.data!.packet, channel),
    onSuccess: () => {
      toast.success("Approved. It goes out under the checks shown.")
      setProblem(null)
      refresh()
    },
    // 409 with the specific code (e.g. packet_superseded), the reason and the gates.
    onError: (e) => {
      setProblem(problemOf(e))
      refresh()
    },
  })
  const send = useMutation({
    mutationFn: () => createDispatch(applicationId),
    onSuccess: (out) => {
      if (out.status === "queued") {
        setProblem(null)
        const held = out.dispatch ? deferredText(out.dispatch, tz) : null
        toast.success(
          held
            ? `${held}. You can cancel it under Autopilot, Sending.`
            : "Queued. You can cancel it under Autopilot, Sending."
        )
      } else setProblem(explainCode(out.code, out.reason, out.gates))
      refresh()
    },
    onError: (e) => setProblem(problemOf(e)),
  })
  // Prepare again (e.g. after confirming the address): the server picks the channel afresh.
  const prepare = useMutation({
    mutationFn: () => preparePacket(applicationId, { channel: "auto" }),
    onSuccess: (out) => {
      setProblem(null)
      setAddressConfirmed(false)
      toast.success(
        out.channel === "email"
          ? "Prepared again: it goes by email once you approve."
          : "Prepared again for you to apply yourself."
      )
      refresh()
    },
    onError: (e) => setProblem(problemOf(e)),
  })
  const decide = useMutation({
    mutationFn: (v: { kind: "changes" | "reject"; text: string }) =>
      v.kind === "reject"
        ? rejectApplication(applicationId, v.text || null)
        : requestChanges(applicationId, v.text),
    onSuccess: (_d, v) => {
      toast.success(
        v.kind === "reject"
          ? "Rejected. Nothing will be sent."
          : "Sent back for changes."
      )
      refresh()
      void navigate({ to: "/approvals" })
    },
    onError: (e) => setProblem(problemOf(e)),
  })

  if (current.isSuccess && current.data === null)
    return (
      <View>
        <BackLink />
        <p className="text-sm text-muted-foreground" role="status">
          No packet has been built for this application yet, so there is nothing
          to approve.
        </p>
      </View>
    )
  if (
    current.isError ||
    app.isError ||
    (receipt.isError && !isApiError(receipt.error, 404))
  )
    return (
      <View>
        <BackLink />
        <p role="alert" className="text-sm text-danger">
          Couldn't load this packet. Try again in a moment.
        </p>
      </View>
    )
  if (!receipt.data || !app.data)
    return (
      <View>
        <BackLink />
        <p className="text-sm text-muted-foreground">Loading the packet.</p>
      </View>
    )

  const r = receipt.data
  const packet = r.packet
  const standing = approvalStanding(packets.data ?? [packet])
  const approvedNow =
    standing.kind === "approved" && standing.packet.version === packet.version
  const heldHere = (held.data ?? []).filter(
    (j) =>
      j.canonical_employer.toLowerCase() === r.employer.toLowerCase() &&
      j.id !== app.data.job_id
  )
  const c = packet.contents

  const submitDecision = (e: FormEvent) => {
    e.preventDefault()
    if (!mode) return
    if (mode === "changes" && !note.trim())
      return setError("Say what should change.")
    decide.mutate({ kind: mode, text: note.trim() })
  }

  return (
    <View className="grid content-start gap-5">
      <BackLink />
      <header className="grid gap-1.5">
        <div className="eyebrow">Review before it is sent</div>
        <h2 className="text-xl">{r.role}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">{r.employer}</span>
          <Chip tone="line" className="num">
            Packet v{packet.version} {shortHash(packet.content_hash)}
          </Chip>
          <Chip tone="line">{CHANNEL_LABEL[channel]}</Chip>
        </div>
      </header>

      {standing.kind === "invalidated" && (
        <div
          role="alert"
          data-testid="approval-invalidated"
          className="flex gap-2.5 rounded-lg border border-border bg-warn-soft p-3 text-warn"
        >
          <OctagonAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="grid gap-0.5 text-sm">
            <b className="font-semibold">
              Your earlier approval no longer applies.
            </b>
            <span>
              You approved version {standing.earlier.version}{" "}
              <span className="num">
                {shortHash(standing.earlier.content_hash)}
              </span>
              {standing.earlier.approved_at &&
                ` on ${stamp(standing.earlier.approved_at)}`}
              . {standing.reason} Nothing is sent until you approve this
              version.
            </span>
          </div>
        </div>
      )}
      {approvedNow && (
        <p className="flex items-center gap-2 text-sm text-good" role="status">
          <CircleCheck className="size-4" aria-hidden="true" />
          Approved by you
          {packet.approved_at && ` on ${stamp(packet.approved_at)}`}. This
          version is the one that will be sent.
        </p>
      )}

      {r.changes_since_last_look.length > 0 && (
        <section
          aria-label="Changed since you last looked"
          className="grid gap-1.5 rounded-lg border border-border bg-warn-soft p-3 text-warn"
        >
          <h4 className="eyebrow text-warn">Changed since you last looked</h4>
          <ul className="grid gap-1 text-sm">
            {r.changes_since_last_look.map((ch) => (
              <li key={ch.path}>
                <b className="font-semibold">{ch.path}:</b>{" "}
                <s className="opacity-75">{String(ch.before)}</s> to{" "}
                {String(ch.after)}
                {ch.material && " (material)"}
              </li>
            ))}
          </ul>
        </section>
      )}

      <WhatWillBeSent contents={c} action={r.action_label} />

      {r.unusual_disclosures.length > 0 && (
        <section aria-label="Also disclosed" className="grid gap-1">
          <h4 className="eyebrow">Also disclosed</h4>
          <ul className="grid gap-0.5 text-sm">
            {r.unusual_disclosures.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </section>
      )}

      <GateList gates={r.gates} />

      {heldHere.length > 0 && (
        <section
          aria-label="Held roles at this employer"
          className="grid gap-2"
        >
          <SectionHeader
            title="Held at this employer"
            aside="One role per employer: the highest score goes ahead."
          />
          <ul className="grid gap-1.5">
            {heldHere.map((j) => (
              <li
                key={j.id}
                className="grid gap-0.5 rounded-md border border-border bg-surface px-3 py-2 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone="warn">Held</Chip>
                  <Link
                    to="/jobs/$id"
                    params={{ id: j.id }}
                    className="font-medium hover:underline"
                  >
                    {j.title}
                  </Link>
                </div>
                <p className="text-muted-foreground">
                  {j.conflict?.outranked_by_title
                    ? `Outranked by ${j.conflict.outranked_by_title}, ${j.conflict.outranked_by_score ?? "?"} vs ${j.conflict.score ?? j.best_score ?? "?"}.`
                    : (j.conflict_note ??
                      "Outranked by another role here.")}{" "}
                  Winner: {r.role}.
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <ConfirmAddressNotice
        job={job.data}
        note={
          channel === "manual"
            ? "This packet was prepared for you to apply yourself."
            : undefined
        }
        onConfirmed={() => setAddressConfirmed(true)}
      />
      {addressConfirmed && channel === "manual" && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 rounded-sm bg-info-soft px-3 py-2 text-sm text-info"
        >
          <span className="min-w-0 flex-1">
            Address confirmed. This packet was built for you to apply yourself;
            prepare it again to send it by email.
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={prepare.isPending}
            onClick={() => prepare.mutate()}
          >
            Prepare again
          </Button>
        </div>
      )}

      {channel === "manual" && <HandoffPanel app={app.data} />}

      {problem && (
        <div role="alert" data-code={problem.code} className="grid gap-2">
          <p className="text-sm text-danger">{problem.text}</p>
          {problem.reason && (
            <p className="text-xs text-muted-foreground">{problem.reason}</p>
          )}
          {problem.action === "reload" && (
            <Button
              size="sm"
              variant="outline"
              className="w-fit"
              onClick={() => {
                setProblem(null)
                refresh()
              }}
            >
              Load the latest version
            </Button>
          )}
          {problem.action === "prepare_again" && (
            <Button
              size="sm"
              variant="outline"
              className="w-fit"
              disabled={prepare.isPending}
              onClick={() => prepare.mutate()}
            >
              Prepare again
            </Button>
          )}
          {problem.action === "resume_autopilot" && (
            <Button asChild size="sm" variant="outline" className="w-fit">
              <Link to="/autopilot">Open the Autopilot</Link>
            </Button>
          )}
          {problem.action === "recheck" && (
            <Button asChild size="sm" variant="outline" className="w-fit">
              <Link to="/studio" search={{ application: applicationId }}>
                Re-run the checks in the Studio
              </Link>
            </Button>
          )}
          {problem.gates.length > 0 && (
            <GateList gates={problem.gates} label="Checks that stopped it" />
          )}
        </div>
      )}
      <footer className="grid gap-3 border-t border-border pt-4">
        {mode ? (
          <form
            onSubmit={submitDecision}
            aria-label={mode === "changes" ? "Request changes" : "Reject"}
            className="flex flex-wrap items-end gap-2"
          >
            <label className="grid gap-1 text-sm font-medium">
              {mode === "changes"
                ? "What should change?"
                : "Why not? (optional)"}
              <Input
                value={note}
                onChange={(e) => {
                  setNote(e.target.value)
                  setProblem(null)
                }}
                className="w-80 max-w-full"
              />
            </label>
            <Button type="submit" disabled={decide.isPending}>
              {mode === "changes"
                ? "Send back for changes"
                : "Reject this role"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setMode(null)
                setNote("")
              }}
            >
              Cancel
            </Button>
          </form>
        ) : (
          <div className="flex flex-wrap gap-2">
            {channel !== "manual" && !approvedNow && (
              <Button
                size="lg"
                disabled={approve.isPending}
                onClick={() => approve.mutate()}
              >
                {r.action_label}
              </Button>
            )}
            {channel !== "manual" && approvedNow && (
              <Button
                size="lg"
                disabled={send.isPending}
                onClick={() => send.mutate()}
              >
                Send now
              </Button>
            )}
            <Button
              variant="outline"
              size="lg"
              onClick={() => setMode("changes")}
            >
              Request changes
            </Button>
            <Button variant="ghost" size="lg" onClick={() => setMode("reject")}>
              Reject
            </Button>
          </div>
        )}
        <p className="text-xs text-faint">
          Approval covers this exact version, {shortHash(packet.content_hash)}.
          If anything in it changes, you are asked again.
        </p>
      </footer>
    </View>
  )
}

function BackLink() {
  return (
    <Button asChild variant="ghost" size="sm" className="w-fit">
      <Link to="/approvals">
        <ArrowLeft aria-hidden="true" />
        Approvals
      </Link>
    </Button>
  )
}

function WhatWillBeSent({
  contents: c,
  action,
}: {
  contents: PacketContents
  action: string
}) {
  const Dest = c.email ? Mail : Globe
  return (
    <section aria-label="What will be sent" className="grid gap-3">
      <SectionHeader title="What will be sent" aside={action} />
      <dl className="grid gap-2 rounded-lg border border-border bg-surface p-3.5 text-sm">
        <Row label="Destination">
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <Dest className="size-4 text-faint" aria-hidden="true" />
            {c.destination.domain}
            {c.destination.verified ? (
              <Chip tone="good" icon={ShieldCheck}>
                Checked
              </Chip>
            ) : (
              <Chip tone="warn">Not verified</Chip>
            )}
            {!c.email && !c.destination.trusted && (
              <Chip tone="warn">Not a trusted site</Chip>
            )}
          </span>
        </Row>
        <Row label="Sent as">{c.sending_identity}</Row>
        {c.requisition && <Row label="Requisition">{c.requisition}</Row>}
        {c.email && (
          <>
            <Row label="To">{c.email.to.join(", ")}</Row>
            {(c.email.cc ?? []).length > 0 && (
              <Row label="Cc">{(c.email.cc ?? []).join(", ")}</Row>
            )}
            <Row label="Subject">{c.email.subject}</Row>
            <Row label="Message">
              <span className="whitespace-pre-wrap">{c.email.body}</span>
            </Row>
          </>
        )}
      </dl>
      <div className="grid gap-1.5">
        <h4 className="eyebrow">Documents</h4>
        <ul className="grid gap-1">
          {c.files.map((f) => (
            <li
              key={f.name}
              className="flex flex-wrap items-center gap-2 text-sm"
            >
              <FileText className="size-4 text-faint" aria-hidden="true" />
              <span className="font-medium">{f.name}</span>
              <Chip tone="line">{f.kind}</Chip>
              <span className="num text-xs text-faint">
                {shortHash(f.sha256)}
              </span>
              {f.share_link && (
                <Chip tone="warn">Shares a link: {f.share_link}</Chip>
              )}
            </li>
          ))}
          {c.files.length === 0 && (
            <li className="text-sm text-muted-foreground">No documents.</li>
          )}
        </ul>
      </div>
      <div className="grid gap-1.5">
        <h4 className="eyebrow">Answers</h4>
        <dl className="grid gap-1.5">
          {c.answers.map((a) => (
            <div key={a.question} className="grid gap-0.5 text-sm">
              <dt className="text-muted-foreground">{a.question}</dt>
              <dd className={a.material ? "font-semibold" : "font-medium"}>
                {a.value}
                {a.material && (
                  <span className="ml-1.5 text-xs font-normal text-faint">
                    material answer
                  </span>
                )}
              </dd>
            </div>
          ))}
          {c.answers.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No form answers. This form needs none.
            </p>
          )}
        </dl>
      </div>
    </section>
  )
}

function Row({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[8rem_1fr]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium">{children}</dd>
    </div>
  )
}
