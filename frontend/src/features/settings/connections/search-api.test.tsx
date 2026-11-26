import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import { aiMockState } from "@/mocks/handlers/ai"
import { renderApp, setupUser } from "@/test/render"
import { checkSearchApi } from "./forms"

const KEY = "sk-example-search-key-1234"

async function openSection() {
  const user = setupUser()
  renderApp("/settings/connections")
  const section = await screen.findByRole("region", { name: "Search API" })
  const form = within(section).getByRole("form", { name: "Add Search API" })
  return { user, section, form }
}

describe("Search API connection", () => {
  it("saves endpoint and shape as config and the key as a write-only secret", async () => {
    const { user, section, form } = await openSection()
    await user.type(
      within(form).getByLabelText("Search address"),
      "https://search.example.com/v1/search"
    )
    await user.type(within(form).getByLabelText("API key"), KEY)
    await user.type(within(form).getByLabelText(/Key header/), "X-API-Key")
    await user.type(
      within(form).getByLabelText(/Result list path/),
      "data.items"
    )
    await user.click(
      within(form).getByRole("button", { name: "Connect search API" })
    )
    const card = await within(section).findByRole("listitem", {
      name: "Search API",
    })
    const saved = aiMockState().connections.find(
      (c) => c.provider === "search_api"
    )!
    expect(saved.config).toEqual({
      endpoint: "https://search.example.com/v1/search",
      key_header: "X-API-Key",
      result_path: "data.items",
    })
    // Only the masked end is shown; the key itself never comes back to the page.
    expect(within(card).getByText("********1234")).toBeInTheDocument()
    expect(document.body.textContent).not.toContain(KEY)
    expect(within(form).getByLabelText("API key")).toHaveValue("")
  })

  it("runs one search when tested", async () => {
    aiMockState().connections.push({
      id: "conn-s",
      created_at: "2026-11-01T00:00:00Z",
      updated_at: "2026-11-01T00:00:00Z",
      provider: "search_api",
      label: "Example search",
      config: { endpoint: "https://search.example.com/v1" },
      secrets_masked: { api_key: "********abcd" },
      scopes_granted: [],
      reads_description: null,
      health: "unknown",
      last_checked_at: null,
      enabled: true,
    })
    const { user, section } = await openSection()
    await user.click(
      await within(section).findByRole("button", {
        name: "Test Example search",
      })
    )
    expect(await within(section).findByRole("status")).toHaveTextContent(
      /Test passed.*provider answered/
    )
  })

  it("refuses a key in both a header and a parameter", async () => {
    const { user, form } = await openSection()
    await user.type(within(form).getByLabelText(/Key header/), "X-API-Key")
    await user.type(within(form).getByLabelText(/Key parameter/), "key")
    expect(within(form).getByRole("alert")).toHaveTextContent(/not both/)
    expect(
      within(form).getByRole("button", { name: "Connect search API" })
    ).toBeDisabled()
  })

  it("changing keeps the saved key when the key field is left empty", async () => {
    aiMockState().connections.push({
      id: "conn-s",
      created_at: "2026-11-01T00:00:00Z",
      updated_at: "2026-11-01T00:00:00Z",
      provider: "search_api",
      label: "Example search",
      config: { endpoint: "https://search.example.com/v1" },
      secrets_masked: { api_key: "********abcd" },
      scopes_granted: [],
      reads_description: null,
      health: "ok",
      last_checked_at: null,
      enabled: true,
    })
    const { user, section } = await openSection()
    await user.click(
      await within(section).findByRole("button", {
        name: "Change Example search",
      })
    )
    const edit = within(section).getByRole("form", {
      name: "Change Example search",
    })
    await user.type(within(edit).getByLabelText(/Title field/), "name")
    await user.click(within(edit).getByRole("button", { name: "Save changes" }))
    await waitFor(() =>
      expect(aiMockState().connections[0].config.title_field).toBe("name")
    )
    expect(aiMockState().connections[0].secrets_masked.api_key).toBe(
      "********abcd"
    )
  })

  it("checkSearchApi allows one key placement", () => {
    expect(checkSearchApi({ key_header: "X-Key" })).toBeNull()
    expect(checkSearchApi({ key_header: "X", key_param: "k" })).toMatch(
      /not both/
    )
  })
})
