import { describe, expect, it } from "vitest"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { renderApp, setupUser } from "@/test/render"
import { server } from "@/test/server"
import { db } from "@/mocks/db"
import { BUILTIN_THEMES } from "@/themes"

/** An owner theme in the mock backend (a copy of Copperbelt), with its first revision. */
function seedOwnerTheme(id = "mine") {
  const { id: _id, builtin: _b, ...body } = BUILTIN_THEMES[0]
  void _id
  void _b
  db.update((s) => {
    s.customThemes.push({ ...body, id, builtin: false, name: "Mine" })
    s.themeRevisions[id] = [
      {
        number: 1,
        parent: null,
        note: "Created",
        actor: "owner",
        created_at: new Date().toISOString(),
        body: { ...body, name: "Mine" },
      },
    ]
    s.themeCurrent[id] = 1
  })
}

async function openStudio(id = "mine") {
  const utils = renderApp(`/theme-studio/${id}`)
  await screen.findByRole("region", { name: /Preview of/ })
  return utils
}

async function textTab(user: ReturnType<typeof setupUser>) {
  await user.click(screen.getByRole("tab", { name: "Text" }))
  return screen.findByRole("textbox", { name: "Text (text)" })
}

describe("Theme studio", () => {
  it("previews the draft in a scope without touching the app's tokens until applied", async () => {
    seedOwnerTheme()
    const user = setupUser()
    await openStudio()
    const root = document.documentElement
    const before = root.style.getPropertyValue("--t-primary")
    expect(before).not.toBe("")
    await user.click(screen.getByRole("tab", { name: "Accent" }))
    const field = await screen.findByRole("textbox", {
      name: "Primary (primary)",
    })
    fireEvent.change(field, { target: { value: "#5A2D82" } })
    const preview = screen.getByTestId("studio-preview")
    await waitFor(() =>
      expect(preview.style.getPropertyValue("--t-primary")).toBe("#5A2D82")
    )
    expect(root.style.getPropertyValue("--t-primary")).toBe(before)

    // Save, then apply: only now does the app root change.
    await user.click(screen.getByRole("button", { name: /^Save$/ }))
    await screen.findByText("Theme saved.")
    await user.click(screen.getByRole("button", { name: /Use this theme/ }))
    await waitFor(() =>
      expect(root.style.getPropertyValue("--t-primary")).toBe("#5A2D82")
    )
  })

  it("blocks saving body text below AA until low contrast is explicitly accepted", async () => {
    seedOwnerTheme()
    const user = setupUser()
    let sent: Record<string, unknown> | null = null
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "PUT" && request.url.includes("/api/themes/mine"))
        sent = (await request.clone().json()) as Record<string, unknown>
    })
    await openStudio()
    // Pin the editor to light mode so the edited token is the one checked.
    await user.click(
      within(
        screen.getByRole("radiogroup", { name: "Editing mode" })
      ).getByRole("radio", { name: /Light/ })
    )
    const text = await textTab(user)
    fireEvent.change(text, { target: { value: "#C8C8C8" } })
    const alert = await screen.findByText(/Body text is below WCAG AA/)
    expect(alert).toBeInTheDocument()
    const save = screen.getByRole("button", { name: /^Save$/ })
    expect(save).toBeDisabled()
    await user.click(
      screen.getByRole("checkbox", { name: /I accept low contrast/ })
    )
    expect(save).toBeEnabled()
    await user.click(save)
    await screen.findByText("Theme saved.")
    await waitFor(() => expect(sent?.accept_low_contrast).toBe(true))
    expect(
      await screen.findByText(/Low contrast accepted on/)
    ).toBeInTheDocument()
    server.events.removeAllListeners()
  })

  it("applies a suggested passing colour", async () => {
    seedOwnerTheme()
    const user = setupUser()
    await openStudio()
    await user.click(
      within(
        screen.getByRole("radiogroup", { name: "Editing mode" })
      ).getByRole("radio", { name: /Light/ })
    )
    const text = await textTab(user)
    fireEvent.change(text, { target: { value: "#C8C8C8" } })
    const fixes = await screen.findAllByRole("button", {
      name: /^Use #[0-9A-F]{6} for Text in light mode/,
    })
    await user.click(fixes[0])
    await waitFor(() =>
      expect(
        screen.queryByText(/Body text is below WCAG AA/)
      ).not.toBeInTheDocument()
    )
  })

  it("renders the colour-blind filter on the preview", async () => {
    seedOwnerTheme()
    const user = setupUser()
    await openStudio()
    const preview = screen.getByTestId("studio-preview")
    expect(preview.dataset.filter).toBe("none")
    await user.selectOptions(
      screen.getByLabelText("Colour vision simulation"),
      "deuteranopia"
    )
    await waitFor(() => expect(preview.dataset.filter).toBe("cvd-deuteranopia"))
    expect(preview.style.filter).toMatch(/^url\("?#cvd-deuteranopia"?\)$/)
    expect(
      document
        .getElementById("cvd-deuteranopia")
        ?.querySelector("feColorMatrix")
    ).not.toBeNull()
  })

  it("keeps built-ins read-only and duplicates to edit", async () => {
    const user = setupUser()
    await openStudio("paper")
    expect(
      screen.getByText(/Built-in themes are read-only/)
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /^Save$/ })
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Duplicate to edit/ }))
    expect(
      await screen.findByRole("heading", { name: /Paper copy/ })
    ).toBeInTheDocument()
    expect(db.get().customThemes.map((t) => t.name)).toContain("Paper copy")
  })

  it("undoes through the server's revisions", async () => {
    seedOwnerTheme()
    const user = setupUser()
    let undone = false
    server.use(
      http.post("*/api/themes/mine/undo", () => {
        undone = true
        return HttpResponse.json(
          { detail: "nothing to go back or forward to" },
          { status: 409 }
        )
      })
    )
    await openStudio()
    await user.click(screen.getByRole("tab", { name: "Basics" }))
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Mine 2" },
    })
    await user.click(screen.getByRole("button", { name: /^Save$/ }))
    await screen.findByText("Theme saved.")
    const undo = await screen.findByRole("button", { name: "Undo" })
    await waitFor(() => expect(undo).toBeEnabled())
    await user.click(undo)
    await waitFor(() => expect(undone).toBe(true))
  })

  it("refuses to delete the active theme", async () => {
    seedOwnerTheme()
    db.update((s) => {
      s.appearance.theme_id = "mine"
    })
    await openStudio()
    const del = screen.getByRole("button", { name: "Delete theme" })
    expect(del).toBeDisabled()
    expect(del).toHaveAttribute("title", expect.stringMatching(/in use/))
  })
})

describe("Appearance: theme files", () => {
  it("rejects an oversize theme file before uploading", async () => {
    let uploaded = false
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/api/themes/import")) uploaded = true
    })
    renderApp("/settings/appearance")
    const input = await screen.findByLabelText("Theme file to import")
    await waitFor(() => expect(db.get().session).toBe(true))
    // The limit comes from the themes.import_max_bytes setting; wait until it has loaded.
    await new Promise((r) => setTimeout(r, 50))
    const big = new File(["x".repeat(70_000)], "big.theme.json", {
      type: "application/json",
    })
    fireEvent.change(input, { target: { files: [big] } })
    expect(
      await screen.findByText(/theme files can be at most 64 KB/)
    ).toBeInTheDocument()
    expect(uploaded).toBe(false)
    server.events.removeAllListeners()
  })

  it("imports a theme file and opens it in the studio", async () => {
    renderApp("/settings/appearance")
    const input = await screen.findByLabelText("Theme file to import")
    const { id: _id, builtin: _b, ...body } = BUILTIN_THEMES[2]
    void _id
    void _b
    const file = new File(
      [
        JSON.stringify({
          format: "nchito-theme",
          version: 1,
          theme: { ...body, name: "Imported dusk" },
        }),
      ],
      "dusk.theme.json",
      {
        type: "application/json",
      }
    )
    await new Promise((r) => setTimeout(r, 50))
    fireEvent.change(input, { target: { files: [file] } })
    expect(
      await screen.findByRole("heading", { name: /Imported dusk/ })
    ).toBeInTheDocument()
  })
})
