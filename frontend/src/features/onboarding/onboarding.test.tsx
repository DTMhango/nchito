import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http } from "msw"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"
import { dataMock, importCalls, importFallback } from "@/mocks/handlers/data"
import { settingRow, writeSetting } from "@/mocks/dataset/settings"
import { isProtectedGroup, groupReview } from "./review-groups"
import {
  EMPTY_DRAFT,
  toCriteria,
  unresolved,
  type CriteriaDraft,
} from "./criteria"
import { CRITERIA } from "./state"

const oldKit = () =>
  new File(["zip"], "old-folder.zip", { type: "application/zip" })

describe("criteria rules", () => {
  it("has no defaults: every criterion is open until entered or deferred", () => {
    expect(unresolved(CRITERIA, EMPTY_DRAFT, [])).toEqual([...CRITERIA])
    expect(unresolved(CRITERIA, EMPTY_DRAFT, [...CRITERIA])).toEqual([])
  })

  it("saves nothing for a criterion marked decide later, even if it was typed", () => {
    const typed: CriteriaDraft = {
      ...EMPTY_DRAFT,
      pay_type: "permanent",
      pay_amount: "4500",
      pay_currency: "zmw",
      pay_period: "month",
      countries: "Zambia",
      seniority: "Head of",
    }
    expect(toCriteria(typed, [])).toMatchObject({
      pay_floors: [{ amount_minor: 450000, currency: "ZMW" }],
      locations: [{ place: "Zambia", kind: "allow" }],
      seniority: ["Head of"],
    })
    expect(toCriteria(typed, ["pay_floor", "countries", "seniority"])).toEqual(
      {}
    )
  })

  it("treats half a pay floor as not entered", () => {
    const half = { ...EMPTY_DRAFT, pay_amount: "4500" }
    expect(unresolved(["pay_floor"], half, [])).toEqual(["pay_floor"])
    expect(toCriteria(half, [])).toEqual({})
  })
})

describe("review groups", () => {
  it("protects pay, countries, seniority, visa and relocation", () => {
    for (const g of [
      "pay_floors",
      "salary",
      "countries",
      "seniority",
      "visa",
      "relocation",
      "work_rights",
    ])
      expect(isProtectedGroup(g)).toBe(true)
    expect(isProtectedGroup("notice")).toBe(false)
  })

  it("lists protected groups first", () => {
    const item = (group: string, rank: number) => ({
      entity: "answer" as const,
      id: group,
      title: group,
      group,
      stale_first_rank: rank,
      conflicts_with: [],
    })
    const order = groupReview([item("notice", 0), item("visa", 5)]).map(
      (g) => g.group
    )
    expect(order).toEqual(["visa", "notice"])
  })
})

describe("Set-up guide: criteria step", () => {
  it("shows empty fields, and Save stays off until each is entered or deferred", async () => {
    const user = userEvent.setup()
    renderApp("/onboarding?step=4")
    const form = await screen.findByRole("form", { name: "Criteria" })
    for (const box of within(form).getAllByRole("textbox"))
      expect(box).toHaveValue("")
    for (const sel of within(form).getAllByRole("combobox"))
      expect(sel).toHaveValue("")
    const save = within(form).getByRole("button", {
      name: "Save criteria and continue",
    })
    expect(save).toBeDisabled()

    await user.click(
      within(form).getByRole("button", { name: "Decide later: Pay floor" })
    )
    expect(save).toBeDisabled()
  })

  it("decide later on all five saves no criteria and warns that automation stays off", async () => {
    const user = userEvent.setup()
    const bodies: { criteria?: Record<string, unknown> }[] = []
    let answerPosts = 0
    server.use(
      http.post("*/api/campaigns", async ({ request }) => {
        bodies.push((await request.clone().json()) as (typeof bodies)[number])
        return undefined
      }),
      http.post("*/api/kit/answers", () => {
        answerPosts++
        return undefined
      })
    )
    renderApp("/onboarding?step=4")
    const form = await screen.findByRole("form", { name: "Criteria" })
    for (const name of [
      "Pay floor",
      "Countries",
      "Seniority",
      "Work rights",
      "Relocation",
    ])
      await user.click(
        within(form).getByRole("button", { name: `Decide later: ${name}` })
      )
    expect(
      screen.getByText(/Until you set these and confirm the campaign/)
    ).toBeInTheDocument()
    await user.click(
      within(form).getByRole("button", { name: "Save criteria and continue" })
    )
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0].criteria).toEqual({})
    expect(answerPosts).toBe(0)
    // Nothing was confirmed, so the campaign cannot go above Prepare.
    await waitFor(() =>
      expect(
        screen.getByRole("navigation", { name: "Set-up steps" })
      ).toBeVisible()
    )
  })

  it("saves what was entered", async () => {
    const user = userEvent.setup()
    const bodies: { criteria?: Record<string, unknown> }[] = []
    server.use(
      http.post("*/api/campaigns", async ({ request }) => {
        bodies.push((await request.clone().json()) as (typeof bodies)[number])
        return undefined
      })
    )
    renderApp("/onboarding?step=4")
    const form = await screen.findByRole("form", { name: "Criteria" })
    await user.selectOptions(
      within(form).getByLabelText("Employment type"),
      "permanent"
    )
    await user.type(within(form).getByLabelText("Amount"), "4500")
    await user.type(within(form).getByLabelText(/Currency/), "ZMW")
    await user.selectOptions(within(form).getByLabelText("Per"), "month")
    await user.type(within(form).getByLabelText("Countries"), "Zambia")
    await user.type(within(form).getByLabelText("Seniority"), "Head of")
    await user.type(within(form).getByLabelText("Work rights"), "Citizen")
    await user.type(within(form).getByLabelText("Relocation"), "Not now")
    await user.click(
      within(form).getByRole("button", { name: "Save criteria and continue" })
    )
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0].criteria).toMatchObject({
      pay_floors: [{ amount_minor: 450000, currency: "ZMW", period: "month" }],
      locations: [{ place: "Zambia", kind: "allow" }],
      seniority: ["Head of"],
    })
  })
})

describe("Set-up guide: old kit import", () => {
  async function importOldKit() {
    importFallback.source = "old_kit_zip"
    const user = userEvent.setup()
    renderApp("/onboarding?step=1")
    await user.click(
      await screen.findByRole("radio", { name: /old job-hunting folder/ })
    )
    const form = await screen.findByRole("form", {
      name: "Choose a file to import",
    })
    await user.upload(within(form).getByLabelText("File"), oldKit())
    await user.click(
      within(form).getByRole("button", { name: "Preview changes" })
    )
    return user
  }

  it("shows the preview first and writes nothing until Import is pressed", async () => {
    importCalls.length = 0
    const user = await importOldKit()
    const preview = await screen.findByRole("region", {
      name: "Import preview",
    })
    expect(within(preview).getByText(/may be stale/)).toBeInTheDocument()
    expect(within(preview).getByText(/to add/)).toBeInTheDocument()
    expect(within(preview).getByText(/1 conflicts/)).toBeInTheDocument()
    // Only the read-only preview call has happened.
    expect(importCalls).toEqual(["preview"])

    await user.click(
      within(preview).getByRole("button", { name: /^Import \d/ })
    )
    await waitFor(() => expect(importCalls).toEqual(["preview", "commit"]))
  })

  it("has no Import button before a preview is on screen", async () => {
    const user = userEvent.setup()
    renderApp("/onboarding?step=1")
    await user.click(
      await screen.findByRole("radio", { name: /old job-hunting folder/ })
    )
    await screen.findByRole("form", { name: "Choose a file to import" })
    expect(screen.queryByRole("button", { name: /^Import \d/ })).toBeNull()
  })

  it("marks every item may be stale and cannot bulk-confirm the protected fields", async () => {
    const user = await importOldKit()
    const preview = await screen.findByRole("region", {
      name: "Import preview",
    })
    await user.click(
      within(preview).getByRole("button", { name: /^Import \d/ })
    )

    for (const group of [
      "pay floors",
      "countries",
      "seniority",
      "visa",
      "relocation",
    ]) {
      const section = await screen.findByRole("region", {
        name: `Review: ${group}`,
      })
      expect(within(section).getByText("May be stale")).toBeInTheDocument()
      expect(within(section).getByText("One by one")).toBeInTheDocument()
      expect(within(section).queryByText(/Confirm these/)).toBeNull()
      expect(within(section).queryByRole("checkbox")).toBeNull()
      expect(
        within(section).getAllByRole("button", { name: /^Confirm / })
      ).toHaveLength(1)
    }
  })

  it("confirms a protected item on its own", async () => {
    const user = await importOldKit()
    const preview = await screen.findByRole("region", {
      name: "Import preview",
    })
    await user.click(
      within(preview).getByRole("button", { name: /^Import \d/ })
    )
    const section = await screen.findByRole("region", {
      name: "Review: pay floors",
    })
    await user.click(
      within(section).getByRole("button", {
        name: "Confirm Pay floor, permanent",
      })
    )
    await waitFor(() =>
      expect(
        screen.queryByRole("region", { name: "Review: pay floors" })
      ).toBeNull()
    )
    // The others are still waiting.
    expect(
      screen.getByRole("region", { name: "Review: countries" })
    ).toBeInTheDocument()
  })
})

describe("Set-up guide: progress from the server", () => {
  const step = (key: string, done: boolean) => ({
    key,
    label: `Label ${key}`,
    done,
    detail: `Detail ${key}.`,
  })

  it("ticks steps only from GET /api/data/onboarding and names the next one", async () => {
    dataMock.onboarding = {
      steps: [
        step("kit_present", true),
        step("facts_confirmed", false),
        step("campaign_exists", true),
        step("criteria_confirmed", true),
        step("mail_connected", false),
      ],
      complete: false,
      next_step: "facts_confirmed",
    }
    renderApp("/onboarding?step=1")
    expect(await screen.findByTestId("next-step")).toHaveTextContent(
      "Label facts_confirmed. Detail facts_confirmed."
    )
    const nav = screen.getByRole("navigation", { name: "Set-up steps" })
    const buttons = within(nav).getAllByRole("button")
    // Step 1 (kit) and step 4 (criteria) are done; step 2 (facts) and 6 (mail) are not.
    expect(within(buttons[0]).queryByLabelText("done")).not.toBeNull()
    expect(within(buttons[1]).queryByLabelText("done")).toBeNull()
    expect(within(buttons[3]).queryByLabelText("done")).not.toBeNull()
    expect(within(buttons[5]).queryByLabelText("done")).toBeNull()
  })

  it("does not count a skipped mailbox as done", async () => {
    dataMock.onboarding = {
      steps: [step("mail_connected", false)],
      complete: false,
      next_step: "mail_connected",
    }
    const user = userEvent.setup()
    renderApp("/onboarding?step=6")
    await user.click(
      await screen.findByRole("button", { name: "Skip for now" })
    )
    const nav = screen.getByRole("navigation", { name: "Set-up steps" })
    await screen.findByRole("heading", { name: "First dry run" })
    expect(
      within(within(nav).getAllByRole("button")[5]).queryByLabelText("done")
    ).toBeNull()
  })
})

describe("Set-up guide: AI notice for an old folder", () => {
  it("asks for acknowledgement before the upload when AI extraction is on", async () => {
    const row = settingRow("data.old_kit_ai_extraction")
    if (row) writeSetting(row, true, null)
    importFallback.source = "old_kit_zip"
    importCalls.length = 0
    const user = userEvent.setup()
    renderApp("/onboarding?step=1")
    await user.click(
      await screen.findByRole("radio", { name: /old job-hunting folder/ })
    )
    const form = await screen.findByRole("form", {
      name: "Choose a file to import",
    })
    const notice = await within(form).findByRole("note", {
      name: "AI provider notice",
    })
    expect(notice).toHaveTextContent(/sent to your AI provider/)
    await user.upload(within(form).getByLabelText("File"), oldKit())
    const previewBtn = within(form).getByRole("button", {
      name: "Preview changes",
    })
    // Nothing can be sent until the owner has read and ticked the notice.
    expect(previewBtn).toBeDisabled()
    expect(importCalls).toEqual([])
    await user.click(within(notice).getByRole("checkbox"))
    expect(previewBtn).toBeEnabled()
    await user.click(previewBtn)
    await screen.findByRole("region", { name: "Import preview" })
    expect(importCalls).toEqual(["preview"])
  })

  it("shows no AI notice while the setting is off", async () => {
    const user = userEvent.setup()
    renderApp("/onboarding?step=1")
    await user.click(
      await screen.findByRole("radio", { name: /old job-hunting folder/ })
    )
    const form = await screen.findByRole("form", {
      name: "Choose a file to import",
    })
    await waitFor(() =>
      expect(
        within(form).queryByRole("note", { name: "AI provider notice" })
      ).toBeNull()
    )
  })
})
