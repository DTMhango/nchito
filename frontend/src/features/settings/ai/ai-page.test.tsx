import { beforeEach, describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { aiMockState, resetAiMock } from "@/mocks/handlers/ai"
import { lineDiff } from "./line-diff"
import { aiKeys } from "./api"

beforeEach(() => resetAiMock())

describe("Settings > AI", () => {
  it("adds a provider and shows its key masked, never in full", async () => {
    const user = userEvent.setup()
    renderApp("/settings/ai")
    const form = await screen.findByRole("form", { name: "Add a provider" })
    await user.type(
      within(form).getByLabelText("API key"),
      "sk-test-abcdefgh1234"
    )
    await user.click(within(form).getByRole("button", { name: "Add provider" }))
    const list = await screen.findByRole("list", { name: "Providers" })
    expect(within(list).getByText("********1234")).toBeInTheDocument()
    expect(screen.queryByText(/abcdefgh1234/)).not.toBeInTheDocument()
  })

  it("only activates a model after a passing route test", async () => {
    const user = userEvent.setup()
    const s = aiMockState()
    s.settings["budget.monthly_cap_minor"] = 2000
    s.connections.push({
      id: "c1",
      created_at: "",
      updated_at: "",
      provider: "anthropic",
      label: "Main",
      config: {},
      secrets_masked: { api_key: "********1234" },
      scopes_granted: [],
      reads_description: null,
      health: "ok",
      last_checked_at: null,
      enabled: true,
    })
    renderApp("/settings/ai")
    const input = await screen.findByLabelText("Model for Score")
    await user.clear(input)
    await user.type(input, "claude-sonnet-5-5")
    const row = input.closest("[role=listitem]") as HTMLElement
    const activate = within(row).getByRole("button", { name: "Activate" })
    expect(activate).toBeDisabled()
    await user.click(within(row).getByRole("button", { name: "Test" }))
    await waitFor(() => expect(activate).toBeEnabled())
    await user.click(activate)
    await waitFor(() =>
      expect(s.settings["ai.model_score"]).toBe("claude-sonnet-5-5")
    )
  })

  it("saves the monthly cap in minor units and shows spend apart from estimates", async () => {
    const user = userEvent.setup()
    renderApp("/settings/ai")
    const cap = await screen.findByLabelText("Monthly cap")
    await user.type(cap, "25")
    await user.click(
      within(cap.closest("form") as HTMLElement).getByRole("button", {
        name: "Save",
      })
    )
    await waitFor(() =>
      expect(aiMockState().settings["budget.monthly_cap_minor"]).toBe(2500)
    )
    expect(
      await screen.findByText("Subscription (not billed)")
    ).toBeInTheDocument()
    expect(screen.getAllByText("$4.12").length).toBeGreaterThan(0)
  })

  it("saves a prompt version, diffs it against the active one and activates it", async () => {
    const user = userEvent.setup()
    renderApp("/settings/ai")
    await user.click(await screen.findByRole("button", { name: "Score" }))
    const text = screen.getByLabelText("Prompt text")
    await user.clear(text)
    await user.type(text, "Score strictly.")
    await user.click(screen.getByRole("button", { name: "Save new version" }))
    expect(
      await screen.findByLabelText("Changes from the active version")
    ).toHaveTextContent("+ Score strictly.")
    await user.click(screen.getByRole("button", { name: "Activate v2" }))
    await waitFor(() =>
      expect(
        aiMockState().prompts.find((p) => p.stage === "score" && p.active)
          ?.version
      ).toBe(2)
    )
  })

  it("feeds the shell spend meter from the summary endpoint", async () => {
    aiMockState().settings["budget.monthly_cap_minor"] = 2500
    localStorage.setItem("nchito.sidebar.collapsed", "0") // expanded sidebar shows the meter
    const { queryClient } = renderApp("/settings/ai")
    await waitFor(() =>
      expect(queryClient.getQueryData(aiKeys.meter)).toMatchObject({
        cap_minor: 2500,
      })
    )
    const meter = screen.getByRole("meter", {
      name: "AI spend against monthly cap",
    })
    expect(meter).toHaveAttribute("aria-valuenow", "16")
  })
})

describe("lineDiff", () => {
  it("marks added and removed lines", () => {
    expect(lineDiff("a\nb\nc", "a\nc\nd")).toEqual([
      { kind: "same", text: "a" },
      { kind: "del", text: "b" },
      { kind: "same", text: "c" },
      { kind: "add", text: "d" },
    ])
  })
})
