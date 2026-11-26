import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import { renderApp, renderWithTheme, setupUser } from "@/test/render"
import { IDS } from "@/mocks/dataset/campaigns"
import { SUGGESTION_IDS } from "@/mocks/dataset/preferences"
import { preferencesMock } from "@/mocks/handlers/preferences"
import { PolicyPreview } from "./policy-preview"
import { SuggestionsPanel } from "./suggestions-panel"

const line = () => screen.getByTestId("preview-line")
const lastPreview = () => preferencesMock.get().requests.previews.at(-1)

describe("policy preview", () => {
  it("moving the auto-apply handle with the keyboard updates the live line", async () => {
    renderWithTheme(<PolicyPreview campaignId={IDS.camp1} />)
    await waitFor(() =>
      expect(line()).toHaveTextContent(
        "At this setting 3 roles would have been applied to in the last 30 days (2 by email, 1 by browser, 1 held as runner-ups)."
      )
    )
    const auto = screen.getByRole("slider", { name: "Auto-apply threshold" })
    expect(auto).toHaveAttribute("aria-valuenow", "85")
    expect(
      screen.getByRole("slider", { name: "Tailor threshold" })
    ).toHaveAttribute("aria-valuenow", "70")

    auto.focus()
    const user = setupUser()
    await user.keyboard("{ArrowLeft}")
    expect(auto).toHaveAttribute("aria-valuenow", "84")
    await waitFor(() =>
      expect(line()).toHaveTextContent(
        "At this setting 4 roles would have been applied to in the last 30 days (2 by email, 2 by browser, 1 held as runner-ups)."
      )
    )
    expect(lastPreview()?.thresholds).toEqual({
      shortlist: 60,
      tailor: 70,
      auto_apply: 84,
    })
    // The histogram stays readable without colour: a labelled image and a table.
    expect(
      screen.getByRole("img", { name: /Scores of 13 roles/ })
    ).toBeVisible()
    expect(screen.getByRole("table")).toBeInTheDocument()
  })

  it("lists changed roles with their reasons, unknowns verbatim and quiet hours", async () => {
    renderWithTheme(<PolicyPreview campaignId={IDS.camp1} />)
    await screen.findByText(
      "1 role with pay not stated: it will never go automatically."
    )
    expect(
      screen.getByText(
        "Right now is inside quiet hours 21:00-07:00: a run now would wait."
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText("No role would be handled differently.")
    ).toBeInTheDocument()

    const user = setupUser()
    screen.getByRole("slider", { name: "Auto-apply threshold" }).focus()
    await user.keyboard("{ArrowLeft}")
    screen.getByRole("slider", { name: "Tailor threshold" }).focus()
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}")

    const list = await screen.findByRole("list", { name: "Changed roles" })
    const risk = await within(list).findByText("Risk Analyst")
    const riskRow = risk.closest("li")!
    expect(riskRow).toHaveTextContent("Newly automatic")
    expect(riskRow).toHaveTextContent("Prepare documents → Apply automatically")
    expect(riskRow).toHaveTextContent(
      "Score 84 is below the auto-apply line 85."
    )
    const lead = (await within(list).findByText("Analytics Lead")).closest(
      "li"
    )!
    expect(lead).toHaveTextContent("Changed")
    expect(lead).toHaveTextContent("Prepare documents → Add to matches")
    expect(lead).toHaveTextContent("Below the tailor line.")
    expect(lastPreview()?.thresholds).toEqual({
      shortlist: 60,
      tailor: 73,
      auto_apply: 84,
    })
  })

  it("sends unsaved proposal pieces with the thresholds", async () => {
    renderWithTheme(
      <PolicyPreview
        campaignId={IDS.camp1}
        settings={{ "automation.daily_cap": 1, "automation.weekly_cap": 5 }}
      />
    )
    await waitFor(() =>
      expect(line()).toHaveTextContent(
        "At this setting 2 roles would have been applied to"
      )
    )
    expect(
      screen.getByText(
        "1 more role qualified but went over the daily or weekly cap.",
        { exact: false }
      )
    ).toBeInTheDocument()
    expect(lastPreview()?.settings).toEqual({
      "automation.daily_cap": 1,
      "automation.weekly_cap": 5,
    })
  })
})

describe("suggestions", () => {
  it("accepts a suggestion: the body is sent, the list updates and the toast says what was created", async () => {
    renderApp(`/campaigns/${IDS.camp1}`)
    const list = await screen.findByRole("list", { name: "Open suggestions" })
    const card = within(list).getByRole("article", {
      name: "Rank roles that ask for a master's degree lower",
    })
    expect(card).toHaveTextContent("Too senior ×3")
    expect(card).toHaveTextContent("“Wants a master's I do not have.”")
    expect(card).toHaveTextContent("Data Scientist, Pricing")
    const user = setupUser()

    // Edit the points, re-run the test, then accept the edited version.
    await user.click(within(card).getByRole("button", { name: "Edit" }))
    const points = within(card).getByRole("spinbutton", { name: "Points" })
    await user.clear(points)
    await user.type(points, "25")
    expect(within(card).getByRole("button", { name: "Accept" })).toBeDisabled()
    await user.click(
      within(card).getByRole("button", { name: "Re-run the test" })
    )
    await waitFor(() =>
      expect(card).toHaveTextContent("3 matched, 5 scores changed")
    )
    expect(preferencesMock.get().requests.backtests.at(-1)?.body).toMatchObject(
      { change: { kind: "add_penalty", points: 25 } }
    )
    await user.click(within(card).getByRole("button", { name: "Accept" }))

    await screen.findByText("Rubric version 2 is now active.")
    const accepted = preferencesMock.get().requests.accepts.at(-1)!
    expect(accepted.id).toBe(SUGGESTION_IDS.penalty)
    expect(accepted.body).toMatchObject({
      change: {
        kind: "add_penalty",
        name: "Asks for a master's degree",
        points: 25,
      },
    })
    await waitFor(() =>
      expect(
        screen.queryByRole("article", {
          name: "Rank roles that ask for a master's degree lower",
        })
      ).not.toBeInTheDocument()
    )
  })

  it("dismisses a suggestion, analyses for new ones, and shows owner-only notes as info", async () => {
    renderWithTheme(<SuggestionsPanel campaignId={IDS.camp1} />)
    const list = await screen.findByRole("list", { name: "Open suggestions" })
    expect(
      screen.getByText(/Suggestions never change seniority/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/3 roles marked down as too senior/)
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText(/open suggestions/)).toHaveTextContent(
        "5 thumbs up, 6 thumbs down, 2 open suggestions."
      )
    )
    const card = within(list).getByRole("article", {
      name: "Give Skills match more weight than Role fit",
    })
    expect(card).toHaveTextContent(
      "Past applications this would have excluded (1)"
    )
    const user = setupUser()
    await user.click(within(card).getByRole("button", { name: "Dismiss" }))
    await waitFor(() =>
      expect(
        screen.queryByRole("article", {
          name: "Give Skills match more weight than Role fit",
        })
      ).not.toBeInTheDocument()
    )
    const dismissed = preferencesMock.get().requests.dismisses.at(-1)!
    expect(dismissed).toEqual({ id: SUGGESTION_IDS.reweight, body: {} })
    expect(preferencesMock.get().requests.accepts).toHaveLength(0)

    await user.click(screen.getByRole("button", { name: "Analyse now" }))
    await screen.findByRole("article", {
      name: "Tag roles at reinsurers as reinsurer",
    })
  })
})
