import { useState } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ConditionBuilder } from "./condition-builder"
import {
  addCondition,
  cleanConditionSet,
  conditionSetSchema,
  emptyConditionSet,
  newCondition,
  withChipState,
} from "./conditions"
import { rubricProblems, weightTotal } from "./rubric"
import {
  effectiveMode,
  isModeAllowed,
  modeCeiling,
  pendingItems,
} from "./automation"
import { BacktestTable } from "./backtest-panel"
import { RubricEditor } from "./rubric-editor"
import { buildDailyCron, parseDailyCron } from "./other-sections"
import { renderApp } from "@/test/render"
import { facets, IDS } from "@/mocks/handlers/campaigns-fixtures"
import { resetCampaignMocks } from "@/mocks/handlers/campaigns"
import type { BacktestRow, ConditionSet, RubricBody } from "./types"

beforeEach(() => resetCampaignMocks())

const crit = (name: string, weight: number) => ({ name, weight, anchors: {} })

describe("rubric weights", () => {
  it("totals the weights and flags anything but 100", () => {
    const ok: RubricBody = { criteria: [crit("A", 60), crit("B", 40)] }
    expect(weightTotal(ok.criteria)).toBe(100)
    expect(rubricProblems(ok)).toEqual([])

    const low = rubricProblems({ criteria: [crit("A", 60), crit("B", 30)] })
    expect(low[0].message).toMatch(/90.*Add 10 more/)
    const high = rubricProblems({ criteria: [crit("A", 70), crit("B", 40)] })
    expect(high[0].message).toMatch(/110.*Take off 10/)
  })

  it("rejects thresholds that do not rise", () => {
    const p = rubricProblems({
      criteria: [crit("A", 100)],
      thresholds: { shortlist: 80, tailor: 70, auto_apply: 85 },
    })
    expect(p.map((x) => x.id)).toContain("thresholds")
  })

  it("shows a live total as weights change", async () => {
    function Harness() {
      const [body, setBody] = useState<RubricBody>({
        criteria: [crit("Fit", 60), crit("Skills", 40)],
      })
      return <RubricEditor body={body} onChange={setBody} catalogue={facets} />
    }
    render(<Harness />)
    const total = screen.getByTestId("weight-total")
    expect(total).toHaveTextContent("100 / 100")
    const weight = screen.getAllByLabelText("Weight")[0]
    await userEvent.clear(weight)
    await userEvent.type(weight, "50")
    expect(total).toHaveTextContent("90 / 100")
    expect(screen.getByText(/Add 10 more/)).toBeInTheDocument()
  })
})

describe("condition builder", () => {
  it("builds output that matches the condition schema", async () => {
    let latest: ConditionSet = emptyConditionSet()
    function Harness() {
      const [v, setV] = useState<ConditionSet>(() =>
        addCondition(
          addCondition(emptyConditionSet(), newCondition(facets[0])),
          newCondition(facets[6])
        )
      )
      latest = v
      return (
        <ConditionBuilder
          label="Test"
          value={v}
          onChange={setV}
          catalogue={facets}
        />
      )
    }
    render(<Harness />)
    const user = userEvent.setup()
    // Visa sponsorship: yes -> include, then "No" twice -> exclude.
    await user.click(
      screen.getByRole("button", {
        name: /Visa sponsorship offered: not filtering.*yes|yes/i,
      })
    )
    const no = screen
      .getAllByRole("button", { name: /no/i })
      .find((b) => /Visa/.test(b.textContent ?? ""))
    expect(no).toBeTruthy()
    await user.click(no!)
    await user.click(no!)
    // Years asked: at least 3, "not stated" keeps the role.
    await user.type(screen.getByLabelText(/at least/i), "3")
    await user.selectOptions(
      screen.getByLabelText(/When it is not stated/i),
      "include"
    )

    const out = cleanConditionSet(latest)
    expect(conditionSetSchema.safeParse(out).success).toBe(true)
    expect(out.root?.conditions).toEqual([
      {
        type: "values",
        facet: "visa_sponsorship",
        include: ["yes"],
        exclude: ["no"],
      },
      {
        type: "range",
        facet: "years_experience",
        min: 3,
        not_stated: "include",
      },
    ])
  })

  it("treats not stated as a value and drops empty conditions", () => {
    const f = withChipState(
      { type: "values", facet: "visa_sponsorship" },
      "not_stated",
      "exclude"
    )
    expect(f).toEqual({
      type: "values",
      facet: "visa_sponsorship",
      exclude: ["not_stated"],
    })
    const set = addCondition(emptyConditionSet(), newCondition(facets[0]))
    expect(cleanConditionSet(set).root?.conditions).toEqual([])
    expect(
      conditionSetSchema.safeParse({ root: { type: "group", bad: 1 } }).success
    ).toBe(false)
  })
})

describe("mode lock", () => {
  it("caps the mode at Prepare until the criteria are confirmed", () => {
    expect(
      modeCeiling({ review_state: "needs_review", mode_ceiling: "auto_apply" })
    ).toBe("prepare")
    expect(
      modeCeiling({ review_state: "confirmed", mode_ceiling: "auto_apply" })
    ).toBe("auto_apply")
    expect(isModeAllowed("ask_then_apply", "prepare")).toBe(false)
    expect(isModeAllowed("save_only", "prepare")).toBe(true)
    expect(effectiveMode("auto_apply", "prepare")).toBe("prepare")
  })

  it("has nothing pre-confirmed: empty pay floors, countries and seniority are 'Not set'", () => {
    const items = pendingItems({ name: "x", criteria: {} })
    expect(items.map((i) => i.value)).toEqual(["Not set", "Not set", "Not set"])
  })

  it("locks the higher modes on an imported campaign and shows why", async () => {
    renderApp(`/campaigns/${IDS.camp2}`)
    const group = await screen.findByRole("radiogroup", {
      name: "Automation mode",
    })
    expect(
      within(group).getByRole("radio", { name: "Ask me, then apply" })
    ).toBeDisabled()
    expect(
      within(group).getByRole("radio", { name: "Apply automatically" })
    ).toBeDisabled()
    expect(
      within(group).getByRole("radio", { name: "Prepare documents" })
    ).toBeChecked()
    expect(
      screen.getByText(/Locked at Prepare documents until you confirm/)
    ).toBeInTheDocument()
    expect(
      screen.getByRole("heading", { name: /Needs your confirmation/ })
    ).toBeInTheDocument()
  })

  it("leaves the modes open on a confirmed campaign", async () => {
    renderApp(`/campaigns/${IDS.camp1}`)
    const group = await screen.findByRole("radiogroup", {
      name: "Automation mode",
    })
    expect(
      within(group).getByRole("radio", { name: "Apply automatically" })
    ).toBeEnabled()
    expect(
      screen.queryByText(/Locked at Prepare documents/)
    ).not.toBeInTheDocument()
  })
})

describe("backtest table", () => {
  const rows: BacktestRow[] = [
    {
      job_id: "a",
      title: "Pricing Actuary",
      employer: "Zambezi Mutual",
      old_score: 68,
      new_score: 74,
      old_rank: 3,
      new_rank: 1,
      crossed: ["tailor_up"],
    },
    {
      job_id: "b",
      title: "Risk Manager",
      employer: "Kafue Re",
      old_score: 86,
      new_score: 80,
      old_rank: 1,
      new_rank: 2,
      crossed: ["auto_down"],
    },
    {
      job_id: "c",
      title: "Data Engineer",
      employer: "Copperline Digital",
      old_score: 50,
      new_score: 50,
      old_rank: 5,
      new_rank: 5,
      crossed: [],
    },
  ]

  it("shows old and new score, rank change and threshold crossings", () => {
    render(<BacktestTable rows={rows} />)
    const table = screen.getByRole("table", {
      name: "Old and new scores for each role",
    })
    const r1 = within(table).getByText("Pricing Actuary").closest("tr")!
    expect(within(r1).getByText("68")).toBeInTheDocument()
    expect(within(r1).getByText(/^74/)).toBeInTheDocument()
    expect(within(r1).getByText("+6")).toBeInTheDocument()
    expect(within(r1).getByLabelText("Rank 3 to 1")).toBeInTheDocument()
    expect(
      within(r1).getByText("Now gets documents prepared")
    ).toBeInTheDocument()
    const r2 = within(table).getByText("Risk Manager").closest("tr")!
    expect(
      within(r2).getByText("No longer eligible to auto-apply")
    ).toBeInTheDocument()
    const r3 = within(table).getByText("Data Engineer").closest("tr")!
    expect(within(r3).getByText("No change")).toBeInTheDocument()
  })

  it("runs a backtest from the editor and offers to make the rubric active", async () => {
    const user = userEvent.setup()
    renderApp(`/campaigns/${IDS.camp1}`)
    await screen.findByRole("heading", { name: /Scoring/ })
    await user.click(
      await screen.findByRole("button", {
        name: /Start a new draft from this version/,
      })
    )
    await user.click(
      await screen.findByRole("button", { name: "Run backtest" })
    )
    const region = await screen.findByRole("region", {
      name: "Backtest results",
    })
    expect(within(region).getByText(/Estimated cost/)).toBeInTheDocument()
    expect(within(region).getByRole("table")).toBeInTheDocument()
    expect(
      within(region).getByRole("button", { name: "Make this rubric active" })
    ).toBeEnabled()
  })
})

describe("schedule helpers", () => {
  it("round-trips a daily time", () => {
    expect(parseDailyCron("30 7 * * 1-5")).toEqual({
      time: "07:30",
      weekdays: true,
    })
    expect(parseDailyCron("0 6,18 * * *")).toBeNull()
    expect(buildDailyCron("07:30", true)).toBe("30 7 * * 1-5")
    expect(buildDailyCron("06:00", false)).toBe("0 6 * * *")
  })
})

describe("preview matches", () => {
  it("says how many saved jobs a rule would catch", async () => {
    const user = userEvent.setup()
    renderApp(`/campaigns/${IDS.camp1}`)
    const rule = await screen.findByRole("article", { name: "Rule 1" })
    await user.click(
      within(rule).getByRole("button", { name: /Preview matches/ })
    )
    await waitFor(() =>
      expect(
        within(rule).getByText(/Would catch 4 of your saved jobs/)
      ).toBeInTheDocument()
    )
  })
})

vi.setConfig({ testTimeout: 20000 })
