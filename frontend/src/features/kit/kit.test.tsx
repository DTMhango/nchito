import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { kitStore, resetKitMock } from "@/mocks/handlers/kit"
import { renderApp } from "@/test/render"
import { summarise } from "./labels"
import type { GuardrailOut } from "./api"

beforeEach(() => resetKitMock())

describe("Kit library", () => {
  it("groups facts under their experience with tags, status and switches", async () => {
    renderApp("/kit/library")
    const card = await screen.findByRole("region", {
      name: "Copperline Mining Services",
    })
    const row = within(card).getByTestId("fact-F-112")
    expect(within(row).getByText("Achievement")).toBeInTheDocument()
    expect(within(row).getByText("#close")).toBeInTheDocument()
    expect(
      within(row).getByRole("button", { name: "Exact wording" })
    ).toHaveAttribute("aria-pressed", "true")
    expect(
      within(card).getByText("Never: Chief Financial Officer")
    ).toBeInTheDocument()
  })

  it("edits a fact in place and saves with Ctrl+Enter", async () => {
    const user = userEvent.setup()
    renderApp("/kit/library")
    await user.click(
      await screen.findByRole("button", { name: "Edit text of F-113" })
    )
    const box = screen.getByLabelText("Text of F-113")
    await user.clear(box)
    await user.type(
      box,
      "Managed a ZMW 500 million budget.{Control>}{Enter}{/Control}"
    )
    await waitFor(() =>
      expect(kitStore().facts.find((f) => f.code === "F-113")?.text).toBe(
        "Managed a ZMW 500 million budget."
      )
    )
  })

  it("toggles keep out of AI prompts straight away", async () => {
    const user = userEvent.setup()
    renderApp("/kit/library")
    const row = await screen.findByTestId("fact-F-114")
    await user.click(
      within(row).getByRole("button", { name: "Keep out of AI" })
    )
    await waitFor(() =>
      expect(
        kitStore().facts.find((f) => f.code === "F-114")?.keep_out_of_prompts
      ).toBe(true)
    )
  })

  it("filters facts by search and by status", async () => {
    const user = userEvent.setup()
    renderApp("/kit/library")
    await screen.findByTestId("fact-F-112")
    await user.type(screen.getByLabelText("Search the library"), "scorecard")
    expect(screen.queryByTestId("fact-F-112")).not.toBeInTheDocument()
    expect(screen.getByTestId("fact-F-121")).toBeInTheDocument()
  })

  it("shows the review count in the sub-nav and confirms an item", async () => {
    const user = userEvent.setup()
    renderApp("/kit/library")
    expect(await screen.findByLabelText("5 to review")).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent(
      "5 items need your review"
    )
    await user.click(screen.getByRole("button", { name: "Needs review only" }))
    expect(screen.queryByTestId("fact-F-112")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Confirm F-131" }))
    await waitFor(() =>
      expect(
        kitStore().facts.find((f) => f.code === "F-131")?.review_state
      ).toBe("confirmed")
    )
    expect(await screen.findByLabelText("4 to review")).toBeInTheDocument()
  })

  it("drops a skill waiting for review", async () => {
    const user = userEvent.setup()
    renderApp("/kit/library")
    await user.click(await screen.findByRole("radio", { name: "Skills" }))
    await user.click(
      await screen.findByRole("button", { name: "Drop Power BI" })
    )
    await waitFor(() =>
      expect(kitStore().skills.some((s) => s.name === "Power BI")).toBe(false)
    )
  })

  it("changes a skill claim and adds a skill", async () => {
    const user = userEvent.setup()
    renderApp("/kit/library")
    await user.click(await screen.findByRole("radio", { name: "Skills" }))
    const group = await screen.findByRole("radiogroup", {
      name: "Claim Python",
    })
    await user.click(within(group).getByRole("radio", { name: "Never" }))
    await waitFor(() =>
      expect(kitStore().skills.find((s) => s.name === "Python")?.claim).toBe(
        "never"
      )
    )
    await user.type(screen.getByLabelText("New skill"), "Budgeting{Enter}")
    await waitFor(() =>
      expect(kitStore().skills.some((s) => s.name === "Budgeting")).toBe(true)
    )
  })
})

describe("Kit tracks", () => {
  it("lists tracks in priority order and moves one down", async () => {
    const user = userEvent.setup()
    renderApp("/kit/tracks")
    const list = await screen.findByRole("list", {
      name: "Tracks in priority order",
    })
    expect(
      within(list).getAllByRole("heading", { level: 3 })[0]
    ).toHaveTextContent("Finance leadership")
    await user.click(
      screen.getByRole("button", { name: "Move Finance leadership down" })
    )
    await waitFor(() =>
      expect(kitStore().tracks.find((t) => t.key === "finance")?.priority).toBe(
        2
      )
    )
    expect(kitStore().tracks.find((t) => t.key === "ops")?.priority).toBe(1)
  })
})

describe("Kit guardrails", () => {
  it("summarises a rule in plain words", () => {
    const g = kitStore().guardrails.find(
      (x) => x.id === "gr-1"
    ) as unknown as GuardrailOut
    expect(summarise(g)).toBe(
      'Never mention "headcount ratio", "staff-to-site ratio" in cv and letter.'
    )
  })

  it("groups rules by type and tests sample text", async () => {
    const user = userEvent.setup()
    renderApp("/kit/guardrails")
    expect(
      await screen.findByRole("region", { name: "Never mention" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("region", { name: "Length limit" })
    ).toBeInTheDocument()
    const tester = screen.getByRole("region", { name: "Test this rule" })
    await user.type(
      within(tester).getByLabelText("Sample text"),
      "Our headcount ratio was confidential."
    )
    await user.click(within(tester).getByRole("button", { name: "Run check" }))
    const results = await within(tester).findByRole("list", {
      name: "Check results",
    })
    expect(results).toHaveTextContent("Confidential headcount ratio")
    expect(results).toHaveTextContent("Blocked")
  })

  it("changes strictness from the row", async () => {
    const user = userEvent.setup()
    renderApp("/kit/guardrails")
    const group = await screen.findByRole("radiogroup", {
      name: "Strictness of Never used Oracle",
    })
    await user.click(within(group).getByRole("radio", { name: "Advise" }))
    await waitFor(() =>
      expect(
        kitStore().guardrails.find((g) => g.id === "gr-2")?.strictness
      ).toBe("advise")
    )
  })
})

describe("Kit answer bank", () => {
  it("filters to answers due for review", async () => {
    const user = userEvent.setup()
    renderApp("/kit/answers")
    expect(
      await screen.findByText("What is your notice period?")
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Due for review/ }))
    expect(
      screen.getByText("Do you require visa sponsorship?")
    ).toBeInTheDocument()
    expect(
      screen.queryByText("What is your notice period?")
    ).not.toBeInTheDocument()
  })

  it("names classes from the owner's side", async () => {
    renderApp("/kit/answers")
    await screen.findByText("What is your notice period?")
    expect(screen.getAllByText("Only me").length).toBeGreaterThan(0)
    expect(screen.queryByText("owner_only")).not.toBeInTheDocument()
  })
})

describe("Kit documents", () => {
  it("uploads a document with its type and sensitivity", async () => {
    const user = userEvent.setup()
    // jsdom's File cannot cross Node's fetch, so catch the multipart POST here.
    const real = globalThis.fetch
    let sent: FormData | null = null
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = input instanceof Request ? input.url : String(input)
      if (url.endsWith("/api/kit/vault") && init?.method === "POST") {
        sent = init.body as FormData
        return Response.json(
          { id: "va-9", title: "reference-letter" },
          { status: 201 }
        )
      }
      return real(input, init)
    })
    renderApp("/kit/documents")
    const form = await screen.findByRole("form", { name: "Upload a document" })
    await user.upload(
      within(form).getByLabelText("File"),
      new File(["x"], "reference-letter.pdf", { type: "application/pdf" })
    )
    expect(within(form).getByLabelText("Title")).toHaveValue("reference-letter")
    await user.selectOptions(
      within(form).getByLabelText("When may it be sent?"),
      "after_offer_only"
    )
    await user.click(within(form).getByRole("button", { name: "Upload" }))
    await waitFor(() => expect(sent).not.toBeNull())
    expect(sent!.get("sensitivity")).toBe("after_offer_only")
    expect(sent!.get("doc_type")).toBe("cv")
    vi.restoreAllMocks()
  })

  it("lists the vault and changes a sensitivity inline", async () => {
    const user = userEvent.setup()
    renderApp("/kit/documents")
    const select = await screen.findByLabelText(
      "Sensitivity of BSc Accounting and Finance"
    )
    await user.selectOptions(select, "after_offer_only")
    await waitFor(() =>
      expect(kitStore().vault.find((d) => d.id === "va-1")?.sensitivity).toBe(
        "after_offer_only"
      )
    )
  })
})

describe("Kit templates", () => {
  it("lists templates with limits and a placeholder for the editor", async () => {
    renderApp("/kit/templates")
    const row = await screen.findByTestId("template-classic")
    expect(row).toHaveTextContent("2 pages, 6 bullets per role")
    expect(
      screen.getByRole("complementary", { name: "Template editor" })
    ).toBeInTheDocument()
  })
})
