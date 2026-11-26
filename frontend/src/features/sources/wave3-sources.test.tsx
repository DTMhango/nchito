import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { store } from "@/mocks/dataset/sources"
import { settingValues } from "@/mocks/dataset/settings"
import { aiMockState } from "@/mocks/handlers/ai"
import { renderApp } from "@/test/render"
import type { Source } from "./api"

const searchConn = (over: Record<string, unknown> = {}) => {
  aiMockState().connections.push({
    id: "conn-search",
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    provider: "search_api",
    label: "Example search",
    config: { endpoint: "https://search.example.com/v1", result_path: "data" },
    secrets_masked: { api_key: "********wxyz" },
    scopes_granted: [],
    reads_description: null,
    health: "ok",
    last_checked_at: null,
    enabled: true,
    ...over,
  })
}

async function openAdd() {
  const user = userEvent.setup()
  renderApp("/sources")
  await user.click(await screen.findByRole("button", { name: "Add source" }))
  const dialog = await screen.findByRole("dialog")
  return { user, dialog }
}

const pick = async (
  user: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
  label: RegExp
) => user.click(within(dialog).getByRole("radio", { name: label }))

describe("Add a careers page source", () => {
  it("saves the employers list under the backend's config keys", async () => {
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /Careers pages/)
    await user.type(
      within(dialog).getByLabelText("Careers page link 1"),
      "https://example.com/careers"
    )
    await user.type(
      within(dialog).getByLabelText("Employer name 1"),
      "Example Ltd"
    )
    await user.click(
      within(dialog).getByRole("button", { name: "Add another page" })
    )
    await user.type(
      within(dialog).getByLabelText("Careers page link 2"),
      "https://example.org/jobs"
    )
    await user.click(within(dialog).getByRole("button", { name: "Add source" }))
    await waitFor(() =>
      expect(store.sources.some((s) => s.connector === "careers_page")).toBe(
        true
      )
    )
    const s = store.sources.find((x) => x.connector === "careers_page")!
    expect(s.access).toBe("html")
    expect(s.config).toEqual({
      employers: [
        { url: "https://example.com/careers", name: "Example Ltd" },
        { url: "https://example.org/jobs" },
      ],
    })
  })

  it("refuses a link that is not a web address before sending", async () => {
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /Careers pages/)
    await user.type(
      within(dialog).getByLabelText("Careers page link 1"),
      "careers page"
    )
    await user.click(within(dialog).getByRole("button", { name: "Add source" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /not a web address/
    )
  })
})

describe("JobSpy", () => {
  it("shows a clear not-installed state instead of failing", async () => {
    store.jobspyInstalled = false
    const before = store.sources.length
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /JobSpy boards/)
    await user.click(within(dialog).getByRole("button", { name: "Add source" }))
    expect(
      await within(dialog).findByText("JobSpy is not installed on this server")
    ).toBeInTheDocument()
    expect(within(dialog).getByText(/nchito\[jobspy\]/)).toBeInTheDocument()
    expect(store.sources.length).toBe(before)
  })

  it("says it is off by default and turns it on through the setting", async () => {
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /JobSpy boards/)
    expect(
      await within(dialog).findByText("JobSpy is switched off")
    ).toBeInTheDocument()
    await user.click(
      within(dialog).getByRole("button", { name: "Turn JobSpy on" })
    )
    await waitFor(() =>
      expect(settingValues["sources.jobspy.enabled"]).toBe(true)
    )
  })

  it("saves board and count overrides checked against the settings", async () => {
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /JobSpy boards/)
    const perBoard = await within(dialog).findByLabelText(
      /JobSpy results per board and query/
    )
    await user.type(perBoard, "500")
    await user.click(within(dialog).getByRole("button", { name: "Add source" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /at most/
    )
    await user.clear(perBoard)
    await user.type(perBoard, "15")
    await user.click(within(dialog).getByRole("checkbox", { name: "linkedin" }))
    await user.click(within(dialog).getByRole("button", { name: "Add source" }))
    await waitFor(() =>
      expect(store.sources.some((s) => s.connector === "jobspy")).toBe(true)
    )
    const s = store.sources.find((x) => x.connector === "jobspy")!
    expect(s.config).toEqual({ boards: ["linkedin"], results_per_board: 15 })
  })

  it("explains a not-installed test result in the drawer", async () => {
    store.jobspyInstalled = false
    store.sources.push({
      ...store.sources[0],
      id: "src-jobspy",
      connector: "jobspy",
      name: "JobSpy boards",
      access: "html",
      config: {},
    } as Source)
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(
      await screen.findByRole("button", {
        name: /JobSpy boards: open settings/,
      })
    )
    await user.click(await screen.findByRole("button", { name: "Test now" }))
    expect(
      await screen.findByText("JobSpy is not installed on this server")
    ).toBeInTheDocument()
  })
})

describe("Web search", () => {
  it("asks for a Search API connection when there is none", async () => {
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /Web search/)
    expect(
      await within(dialog).findByText("No Search API connection yet.")
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole("link", { name: "Add a Search API connection" })
    ).toHaveAttribute("href", "/settings/connections")
  })

  it("uses the first enabled connection and copies its shape, not its key", async () => {
    searchConn()
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /Web search/)
    expect(
      await within(dialog).findByText(/now Example search/)
    ).toBeInTheDocument()
    await user.click(within(dialog).getByRole("button", { name: "Add source" }))
    await waitFor(() =>
      expect(store.sources.some((s) => s.connector === "web_search")).toBe(true)
    )
    const s = store.sources.find((x) => x.connector === "web_search")!
    expect(s.access).toBe("api")
    expect(s.config).toEqual({
      endpoint: "https://search.example.com/v1",
      result_path: "data",
    })
    expect(JSON.stringify(s.config)).not.toContain("wxyz")
  })

  it("names a chosen connection with connection_id", async () => {
    searchConn()
    const { user, dialog } = await openAdd()
    await pick(user, dialog, /Web search/)
    await user.selectOptions(
      await within(dialog).findByLabelText("Search API connection"),
      "conn-search"
    )
    await user.click(within(dialog).getByRole("button", { name: "Add source" }))
    await waitFor(() =>
      expect(
        store.sources.find((s) => s.connector === "web_search")?.config
          ?.connection_id
      ).toBe("conn-search")
    )
  })
})

describe("Discovery settings tab", () => {
  it("lists the sources settings group", async () => {
    const user = userEvent.setup()
    renderApp("/sources")
    await user.click(
      await screen.findByRole("tab", { name: "Discovery settings" })
    )
    expect(await screen.findByText("Web search phrase")).toBeInTheDocument()
    expect(
      screen.getByText("Careers page postings per employer")
    ).toBeInTheDocument()
  })
})
