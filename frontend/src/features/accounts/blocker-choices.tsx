import { useId, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { errorText } from "@/features/autopilot/api"
import {
  giveUp,
  resolvePendingAction,
  type GiveUpOut,
  type PendingAction,
} from "./api"
import {
  ACKNOWLEDGE_TEXT,
  CHOICE_LABEL,
  acknowledgedBody,
  choicesOf,
  continueBody,
  continueErrorText,
  continueRule,
  giveUpBody,
  type OwnerChoice,
} from "./logic"

export type ChoiceResult =
  | { choice: "continue" | "continue_acknowledged"; action: PendingAction }
  | { choice: "manual_handoff" | "skipped"; gaveUp: GiveUpOut }

/**
 * The owner's choices for an open runner blocker, exactly as the server lists them
 * (`PendingActionOut.choices`): continue, the acknowledged continue of a suspicious page, apply
 * myself instead, or skip. No choice is offered that the server did not list.
 */
export function BlockerChoices({
  action,
  applicationIds = null,
  disabled = false,
  size = "default",
  onDone,
}: {
  action: PendingAction
  /** For apply myself / skip: the applications chosen; null means every waiting one. */
  applicationIds?: string[] | null
  disabled?: boolean
  size?: "default" | "sm"
  onDone: (r: ChoiceResult) => void
}) {
  const choices = choicesOf(action)
  const rule = continueRule(action)
  const [acking, setAcking] = useState(false)
  const [ack, setAck] = useState(false)
  const [note, setNote] = useState("")
  const [error, setError] = useState<string | null>(null)
  const ackId = useId()

  const act = useMutation({
    mutationFn: async (choice: OwnerChoice): Promise<ChoiceResult> => {
      if (choice === "continue") {
        if (!rule) throw new Error("This one cannot be continued.")
        return {
          choice,
          action: await resolvePendingAction(action.id, continueBody(rule)),
        }
      }
      if (choice === "continue_acknowledged")
        return {
          choice,
          action: await resolvePendingAction(action.id, acknowledgedBody(note)),
        }
      return {
        choice,
        gaveUp: await giveUp(
          action.id,
          giveUpBody(
            choice === "manual_handoff" ? "apply_myself" : "skip",
            applicationIds
          )
        ),
      }
    },
    onSuccess: (r) => {
      setError(null)
      onDone(r)
    },
    onError: (e) => setError(continueErrorText(e, errorText(e))),
  })

  if (choices.length === 0) return null
  const busy = disabled || act.isPending
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        {choices.map((c) =>
          c === "continue" ? (
            <Button
              key={c}
              size={size}
              disabled={busy}
              onClick={() => act.mutate("continue")}
            >
              {rule?.label}
            </Button>
          ) : c === "continue_acknowledged" ? (
            <Button
              key={c}
              size={size}
              variant="outline"
              aria-expanded={acking}
              disabled={busy}
              onClick={() => setAcking((v) => !v)}
            >
              {CHOICE_LABEL[c]}
            </Button>
          ) : (
            <Button
              key={c}
              size={size}
              variant={c === "skipped" ? "ghost" : "outline"}
              disabled={busy}
              onClick={() => act.mutate(c)}
            >
              {CHOICE_LABEL[c]}
            </Button>
          )
        )}
      </div>
      {acking && (
        <div
          role="group"
          aria-label="Continue on this page"
          className="grid gap-2 rounded-md bg-warn-soft p-3 text-sm"
        >
          <p>
            The runner stopped because this page looked wrong. Look at it
            yourself first. It carries on only if you say it is safe.
          </p>
          <label htmlFor={ackId} className="flex items-start gap-2">
            <input
              id={ackId}
              type="checkbox"
              className="mt-1"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
            />
            {ACKNOWLEDGE_TEXT}
          </label>
          <label className="grid max-w-md gap-1">
            Note for the record (optional)
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div>
            <Button
              size="sm"
              disabled={!ack || busy}
              onClick={() => act.mutate("continue_acknowledged")}
            >
              Continue on this page
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  )
}
