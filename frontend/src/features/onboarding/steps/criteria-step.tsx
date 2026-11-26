import { useId, useState, type ReactNode } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { api, unwrap } from "@/lib/api/client"
import { useSave, type AnswerIn, type AnswerOut } from "@/features/kit/api"
import { saveCampaign } from "@/features/campaigns/api"
import {
  CRITERION_LABEL,
  EMPTY_DRAFT,
  payState,
  toCriteria,
  unresolved,
  type CriteriaDraft,
} from "../criteria"
import { CRITERIA, type CriterionKey, type Local } from "../state"

const SELECT =
  "h-8 w-full min-w-0 rounded-md border field-focus border-input bg-surface px-2 text-base text-foreground outline-none"

const FIRST_CAMPAIGN = "First search"

const createCampaign = (criteria: ReturnType<typeof toCriteria>) =>
  unwrap(
    api.POST("/api/campaigns", { body: { name: FIRST_CAMPAIGN, criteria } })
  )

export function CriteriaStep({
  local,
  update,
  next,
}: {
  local: Local
  update: (p: Partial<Local>) => void
  next: () => void
}) {
  const qc = useQueryClient()
  const uid = useId()
  const [d, setD] = useState<CriteriaDraft>(EMPTY_DRAFT)
  const saveAnswer = useSave<AnswerOut, AnswerIn>("answers")
  const later = local.decideLater
  const open = unresolved(CRITERIA, d, later)
  const set = (k: keyof CriteriaDraft) => (e: { target: { value: string } }) =>
    setD((cur) => ({ ...cur, [k]: e.target.value }))
  const toggle = (k: CriterionKey) =>
    update({
      decideLater: later.includes(k)
        ? later.filter((x) => x !== k)
        : [...later, k],
    })

  const save = useMutation({
    mutationFn: async () => {
      const criteria = toCriteria(d, later)
      const camp = local.campaignId
        ? await saveCampaign(local.campaignId, {
            name: FIRST_CAMPAIGN,
            criteria,
          })
        : await createCampaign(criteria)
      const ids = { ...local.answerIds }
      const text: [CriterionKey, string, string][] = [
        ["work_rights", "Do you have the right to work here?", d.work_rights],
        ["relocation", "Would you relocate?", d.relocation],
      ]
      for (const [key, canonical, value] of text) {
        if (later.includes(key) || !value.trim()) continue
        const row = await saveAnswer.mutateAsync({
          id: ids[key],
          body: {
            patterns: { canonical },
            value: value.trim(),
            answer_class: "ask_first",
            material: true,
            settled: false,
          },
        })
        ids[key] = row.id
      }
      return { id: camp.id, ids }
    },
    onSuccess: ({ id, ids }) => {
      update({ campaignId: id, answerIds: ids })
      void qc.invalidateQueries({ queryKey: ["campaigns"] })
      next()
    },
  })

  const block = (
    key: CriterionKey,
    hint: string,
    children: ReactNode
  ): ReactNode => {
    const deferred = later.includes(key)
    return (
      <fieldset
        key={key}
        className="grid gap-2 rounded-md border border-border bg-surface p-3"
      >
        <legend className="px-1 font-semibold">{CRITERION_LABEL[key]}</legend>
        <p className="text-sm text-muted-foreground">{hint}</p>
        <div className="grid gap-2" aria-disabled={deferred} inert={deferred}>
          {children}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant={deferred ? "default" : "outline"}
            aria-pressed={deferred}
            aria-label={`Decide later: ${CRITERION_LABEL[key]}`}
            onClick={() => toggle(key)}
          >
            Decide later
          </Button>
          {deferred && (
            <span className="text-sm text-warn">
              Automation stays off until you decide this.
            </span>
          )}
        </div>
      </fieldset>
    )
  }

  const pay = payState(d)
  return (
    <form
      aria-label="Criteria"
      className="grid max-w-[640px] gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (open.length === 0) save.mutate()
      }}
    >
      <p className="text-muted-foreground">
        Nothing here is filled in for you. Enter each one, or choose Decide
        later. An item you decide later is left empty and keeps automation off.
      </p>

      {block(
        "pay_floor",
        "The lowest pay you would consider, per kind of employment.",
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="grid gap-1">
            <span>Employment type</span>
            <select
              className={SELECT}
              value={d.pay_type}
              onChange={set("pay_type")}
            >
              <option value="">Choose</option>
              <option value="permanent">Permanent</option>
              <option value="fixed_term">Fixed term</option>
              <option value="contract">Contract</option>
              <option value="eor">Employer of record</option>
            </select>
          </label>
          <label className="grid gap-1">
            <span>Amount</span>
            <Input
              inputMode="decimal"
              className="num"
              value={d.pay_amount}
              onChange={set("pay_amount")}
            />
          </label>
          <label className="grid gap-1">
            <span>Currency (3 letters)</span>
            <Input
              maxLength={3}
              value={d.pay_currency}
              onChange={set("pay_currency")}
            />
          </label>
          <label className="grid gap-1">
            <span>Per</span>
            <select
              className={SELECT}
              value={d.pay_period}
              onChange={set("pay_period")}
            >
              <option value="">Choose</option>
              <option value="year">Year</option>
              <option value="month">Month</option>
              <option value="week">Week</option>
              <option value="day">Day</option>
              <option value="hour">Hour</option>
            </select>
          </label>
          {pay === "partial" && !later.includes("pay_floor") && (
            <p className="text-sm text-danger sm:col-span-2">
              Fill in all four, with a plain amount like 4500 or 4500.50.
            </p>
          )}
        </div>
      )}

      {block(
        "countries",
        "Countries you would take a job in, separated by commas.",
        <label className="grid gap-1">
          <span>Countries</span>
          <Input value={d.countries} onChange={set("countries")} />
        </label>
      )}

      {block(
        "seniority",
        "Levels you would take, separated by commas.",
        <label className="grid gap-1">
          <span>Seniority</span>
          <Input value={d.seniority} onChange={set("seniority")} />
        </label>
      )}

      {block(
        "work_rights",
        "Where you are allowed to work, and on what terms. This is saved as an answer you confirm later.",
        <label className="grid gap-1">
          <span>Work rights</span>
          <Textarea
            id={`${uid}-wr`}
            rows={2}
            value={d.work_rights}
            onChange={set("work_rights")}
          />
        </label>
      )}

      {block(
        "relocation",
        "Whether you would move, where to, and what you would need. Saved as an answer you confirm later.",
        <label className="grid gap-1">
          <span>Relocation</span>
          <Textarea
            rows={2}
            value={d.relocation}
            onChange={set("relocation")}
          />
        </label>
      )}

      {open.length > 0 && (
        <p role="status" className="text-sm text-muted-foreground">
          Still to enter or defer:{" "}
          {open.map((k) => CRITERION_LABEL[k]).join(", ")}.
        </p>
      )}
      {later.length > 0 && (
        <p
          role="status"
          className="rounded-sm bg-warn-soft px-3 py-2 text-warn"
        >
          Deciding later: {later.map((k) => CRITERION_LABEL[k]).join(", ")}.
          Until you set these and confirm the campaign, nothing is sent
          automatically.
        </p>
      )}
      <div>
        <Button type="submit" disabled={open.length > 0 || save.isPending}>
          Save criteria and continue
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
