import { describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { renderApp } from "@/test/render"
import { server } from "@/test/server"
import {
  STUDIO_BUDGET,
  STUDIO_DRAFTED,
  STUDIO_FRESH,
} from "@/mocks/dataset/studio"
import { markStale, studioMock } from "@/mocks/handlers/studio"

// The whole app mounts per test; give a busy machine room.
configure({ asyncUtilTimeout: 8000 })

/** Make the drafted application ready to send: checks pass, no question waits on the owner. */
function makeSendable() {
  const e = studioMock().entries[STUDIO_DRAFTED]
  e.check_results = [
    {
      check: "fact_trace",
      status: "pass",
      detail: null,
      guardrail_id: null,
      waived: false,
    },
  ]
  e.answers = e.answers.filter((a) => a.outcome !== "ask_owner")
}

const open = async (id: string) => {
  renderApp(`/studio?application=${id}`)
  return screen.findByRole("heading", {
    name: /Pricing Actuary|Risk Data Manager|Head of Data/,
  })
}
const claimWith = async (text: string | RegExp) => {
  const box = await screen.findByDisplayValue(text)
  return box.closest("[data-claim]") as HTMLElement
}

describe("Studio", { timeout: 30_000 }, () => {
  it("flags a claim with no fact behind it, and clears the flag once a fact is cited", async () => {
    const user = userEvent.setup()
    await open(STUDIO_DRAFTED)
    const untraced = await claimWith(/Introduced rolling forecasts/)
    expect(untraced).toHaveAttribute("data-trace", "untraced")
    expect(
      within(untraced).getByText("Untraced: no fact behind this claim")
    ).toBeInTheDocument()
    // a traced claim carries its fact tag and no flag
    const traced = await claimWith(/Led a team of six analysts/)
    expect(traced).toHaveAttribute("data-trace", "traced")
    expect(
      within(traced).getByRole("button", { name: /^F-101, approved/ })
    ).toBeInTheDocument()
    expect(within(traced).queryByText(/Untraced/)).not.toBeInTheDocument()

    await user.selectOptions(
      within(untraced).getByRole("combobox", { name: /Cite a fact/ }),
      within(untraced).getByRole("option", { name: /^F-102/ })
    )
    expect(untraced).toHaveAttribute("data-trace", "traced")
    expect(within(untraced).queryByText(/Untraced/)).not.toBeInTheDocument()
  })

  it("marks the checks stale after an edit, and current again after a re-check", async () => {
    const user = userEvent.setup()
    await open(STUDIO_DRAFTED)
    const state = await screen.findByText("Up to date")
    expect(state).toHaveAttribute("data-check-state", "current")

    const box = await screen.findByDisplayValue(/Wrote production SQL/)
    await user.type(box, " daily")
    expect(
      await screen.findByText("Edited since last check")
    ).toBeInTheDocument()
    expect(
      screen.getByText(/You edited the draft after the last check/)
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Send for approval" })
    ).toBeDisabled()

    await user.click(screen.getByRole("button", { name: /Re-check/ }))
    expect(await screen.findByText("Up to date")).toBeInTheDocument()
    expect(
      screen.queryByText("Edited since last check")
    ).not.toBeInTheDocument()
  })

  it("offers a waiver for a waivable rule, with a required reason, and never for an always-block rule", async () => {
    const user = userEvent.setup()
    await open(STUDIO_DRAFTED)
    const blocking = await screen.findByRole("group", { name: "Blocking" })

    const always = within(blocking)
      .getByText("Budget and headcount together")
      .closest("li") as HTMLElement
    expect(
      within(always).queryByRole("button", { name: /Waive/ })
    ).not.toBeInTheDocument()
    expect(within(always).getByText(/always blocks/)).toBeInTheDocument()

    const tracing = within(blocking)
      .getByText("Fact tracing")
      .closest("li") as HTMLElement
    expect(
      within(tracing).queryByRole("button", { name: /Waive/ })
    ).not.toBeInTheDocument()

    const waivable = within(blocking)
      .getByText("Never used Oracle")
      .closest("li") as HTMLElement
    await user.click(
      within(waivable).getByRole("button", { name: /Waive once/ })
    )
    const dialog = await screen.findByRole("dialog")
    const submit = within(dialog).getByRole("button", {
      name: "Waive for this application",
    })
    expect(submit).toBeDisabled()
    await user.type(
      within(dialog).getByLabelText(/Reason/),
      "The posting names Oracle; I list it as a system I report from."
    )
    await user.click(submit)
    expect(await screen.findByText("Waived once")).toBeInTheDocument()
    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Blocking" })).queryByText(
          "Never used Oracle"
        )
      ).not.toBeInTheDocument()
    )
  })

  it("never shows an unknown or unconfirmed answer as yes", async () => {
    const user = userEvent.setup()
    await open(STUDIO_DRAFTED)
    await user.click(
      await screen.findByRole("tab", { name: /Screening answers/ })
    )

    const relocate = await screen.findByRole("group", {
      name: "Are you willing to relocate to Kitwe?",
    })
    expect(relocate).toHaveAttribute("data-standing", "ask_owner")
    expect(within(relocate).getByText("Needs your answer")).toBeInTheDocument()
    expect(within(relocate).queryByText(/^Yes$/)).not.toBeInTheDocument()
    expect(relocate.textContent).not.toMatch(/\bYes\b/)
    // it links to the unknown_question pending action that asks
    expect(
      within(relocate).getByRole("link", {
        name: "Answer the question on Today",
      })
    ).toHaveAttribute("data-action-id", "c0000000-0000-4000-8000-000000000402")

    const sponsorship = screen.getByRole("group", {
      name: "Do you require visa sponsorship?",
    })
    expect(sponsorship).toHaveAttribute("data-standing", "ask_owner")
    expect(sponsorship.textContent).not.toMatch(/\bNo\b/)

    const gender = screen.getByRole("group", { name: "What is your gender?" })
    expect(gender).toHaveAttribute("data-standing", "declined")

    const notice = screen.getByRole("group", {
      name: "What is your notice period?",
    })
    expect(within(notice).getByText("One month")).toBeInTheDocument()

    // nor in the preview of what will be sent
    const preview = screen.getByRole("region", { name: "Answers preview" })
    expect(preview.textContent).not.toMatch(/\bYes\b/)
    expect(
      within(preview).getAllByText("Waiting for your answer").length
    ).toBeGreaterThan(0)
  })

  it("shows a budget-paused tailoring with its cost and a link to Settings > AI", async () => {
    const user = userEvent.setup()
    await open(STUDIO_BUDGET)
    await user.click(
      await screen.findByRole("button", { name: /Tailor this application/ })
    )
    expect(
      await screen.findByRole("heading", {
        name: /Paused: the AI budget is used up/,
      })
    ).toBeInTheDocument()
    expect(screen.getByTestId("tailor-cost")).toHaveTextContent("$0.0042")
    expect(screen.getByRole("link", { name: /Settings › AI/ })).toHaveAttribute(
      "href",
      "/settings/ai"
    )
  })

  it("shows tailoring in progress, then the draft", async () => {
    const user = userEvent.setup()
    await open(STUDIO_FRESH)
    await user.click(
      await screen.findByRole("button", { name: /Tailor this application/ })
    )
    expect(
      await screen.findByRole("heading", { name: "Tailoring this application" })
    ).toBeInTheDocument()
    expect(
      await screen.findByDisplayValue(
        /Led a team of six analysts/,
        {},
        { timeout: 10000 }
      )
    ).toBeInTheDocument()
    expect(screen.getByTestId("tailor-cost-chip")).toHaveTextContent("$0.04")
  })

  it("lists applications to open when none is chosen", async () => {
    renderApp("/studio")
    expect(
      await screen.findByRole("heading", { name: "Choose an application" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /Pricing Actuary/ })
    ).toHaveAttribute(
      "href",
      expect.stringContaining(`application=${STUDIO_DRAFTED}`)
    )
  })

  it("takes the stale state and its reasons from the server, and clears it with a re-check", async () => {
    const user = userEvent.setup()
    markStale(STUDIO_DRAFTED, ["F-101 changed after the last check."])
    await open(STUDIO_DRAFTED)
    const chip = await screen.findByText("Out of date")
    expect(chip).toHaveAttribute("data-check-state", "stale")
    expect(
      screen.getByText("F-101 changed after the last check.")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Send for approval" })
    ).toBeDisabled()

    await user.click(screen.getByRole("button", { name: /Re-check/ }))
    expect(await screen.findByText("Up to date")).toBeInTheDocument()
    expect(screen.queryByText("Out of date")).not.toBeInTheDocument()
  })

  it("shows the renderer's layout warnings for the chosen template", async () => {
    const user = userEvent.setup()
    await open(STUDIO_DRAFTED)
    const picker = await screen.findByRole("combobox", { name: "Template" })
    expect(screen.getByTestId("template-source")).toHaveTextContent(
      /your documents setting/
    )
    expect(
      screen.queryByRole("list", { name: "Layout warnings" })
    ).not.toBeInTheDocument()

    await user.selectOptions(picker, "compact")
    const warnings = await screen.findByRole("list", {
      name: "Layout warnings",
    })
    expect(warnings).toHaveTextContent(
      "Head of Finance Operations has 6 bullets; Compact allows 4."
    )
  })

  it("builds the packet and opens its approval", async () => {
    const user = userEvent.setup()
    makeSendable()
    const { router } = renderApp(`/studio?application=${STUDIO_DRAFTED}`)
    const send = await screen.findByRole("button", {
      name: "Send for approval",
    })
    await waitFor(() => expect(send).toBeEnabled())
    await user.click(send)
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        `/approvals/${STUDIO_DRAFTED}`
      )
    )
    const packet = studioMock().entries[STUDIO_DRAFTED].packets[0]
    expect(packet.contents.files.map((f) => f.kind)).toEqual(["cv", "letter"])
    expect(packet.contents.files.every((f) => !!f.document_id)).toBe(true)
    // only answered questions travel; the declined one stays out
    expect(packet.contents.answers.map((a) => a.question)).toEqual([
      "What is your notice period?",
    ])
  })

  it("explains a refusal to build the packet and offers to re-run the checks", async () => {
    const user = userEvent.setup()
    makeSendable()
    server.use(
      http.post("*/api/applications/:id/packet", () =>
        HttpResponse.json(
          { detail: "the spec changed after its check" },
          { status: 409 }
        )
      )
    )
    const { router } = renderApp(`/studio?application=${STUDIO_DRAFTED}`)
    const send = await screen.findByRole("button", {
      name: "Send for approval",
    })
    await waitFor(() => expect(send).toBeEnabled())
    await user.click(send)
    const alert = await screen.findByText(/The checks are out of date/)
    expect(alert.closest("[role=alert]")).not.toBeNull()
    expect(
      screen.getByRole("button", { name: "Re-run the checks" })
    ).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/studio")
  })
})
