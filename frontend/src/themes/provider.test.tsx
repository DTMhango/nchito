import { act, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { db } from "@/mocks/db"
import { renderWithTheme } from "@/test/render"
import { setSystemDark } from "@/test/media"
import { APPEARANCE_KEY, PAINT_KEY } from "./cache"
import { useTheme } from "./provider"
import { ThemeScope } from "./scope"

const root = () => document.documentElement
const token = (name: string) => root().style.getPropertyValue(`--t-${name}`)

function Controls() {
  const { theme, mode, setAppearance } = useTheme()
  return (
    <div>
      <span data-testid="state">
        {theme.id}/{mode}
      </span>
      <button onClick={() => setAppearance({ theme_id: "midnight-ledger" })}>
        midnight
      </button>
      <button onClick={() => setAppearance({ mode: "dark" })}>dark</button>
      <button onClick={() => setAppearance({ mode: "system" })}>system</button>
    </div>
  )
}

describe("ThemeProvider", () => {
  it("applies the default theme's tokens to the root element", async () => {
    db.reset("signed-out")
    renderWithTheme(<Controls />)
    await waitFor(() => expect(token("bg")).toBe("#F2F5F3"))
    expect(root().dataset.themeId).toBe("copperbelt")
    expect(root().dataset.mode).toBe("light")
  })

  it("follows the device in system mode and reacts when it changes", async () => {
    db.reset("signed-out")
    renderWithTheme(<Controls />)
    await waitFor(() => expect(root().dataset.mode).toBe("light"))
    act(() => setSystemDark(true))
    await waitFor(() => expect(root().dataset.mode).toBe("dark"))
    expect(token("bg")).toBe("#0C1513")
  })

  it("persists changes to the API and the local cache, optimistically", async () => {
    const user = userEvent.setup()
    renderWithTheme(<Controls />)
    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent("copperbelt/light")
    )

    await user.click(screen.getByText("midnight"))
    // Applied at once, before the server answers.
    expect(root().dataset.themeId).toBe("midnight-ledger")
    await waitFor(() =>
      expect(db.get().appearance.theme_id).toBe("midnight-ledger")
    )

    await user.click(screen.getByText("dark"))
    await waitFor(() => expect(db.get().appearance.mode).toBe("dark"))
    expect(token("bg")).toBe("#0B1020")

    const cached = JSON.parse(localStorage.getItem(APPEARANCE_KEY)!)
    expect(cached.appearance).toMatchObject({
      theme_id: "midnight-ledger",
      mode: "dark",
    })
    const paint = JSON.parse(localStorage.getItem(PAINT_KEY)!)
    expect(paint.dark["--t-bg"]).toBe("#0B1020")
  })

  it("loads the saved appearance from the API after sign-in", async () => {
    db.update((s) => {
      s.appearance = { ...s.appearance, theme_id: "workshop", mode: "dark" }
    })
    renderWithTheme(<Controls />)
    await waitFor(() =>
      expect(screen.getByTestId("state")).toHaveTextContent("workshop/dark")
    )
    expect(token("bg")).toBe("#15171A")
  })

  it("starts from the local cache before the API answers", async () => {
    db.reset("signed-out")
    localStorage.setItem(
      APPEARANCE_KEY,
      JSON.stringify({
        appearance: {
          theme_id: "paper",
          mode: "light",
          density: "comfortable",
          radius: null,
          font_scale: 1,
          accent_override: null,
          reduced_motion: false,
        },
        theme: null,
      })
    )
    renderWithTheme(<Controls />)
    expect(screen.getByTestId("state")).toHaveTextContent("paper/light")
    expect(token("bg")).toBe("#FBFBFC")
  })
})

describe("ThemeScope", () => {
  it("renders a subtree in another theme and mode", async () => {
    db.reset("signed-out")
    renderWithTheme(
      <ThemeScope theme="savanna-dusk" mode="dark" data-testid="scope">
        <span>inside</span>
      </ThemeScope>
    )
    const scope = screen.getByTestId("scope")
    expect(scope).toHaveAttribute("data-theme-scope")
    expect(scope).toHaveAttribute("data-mode", "dark")
    expect(scope.style.getPropertyValue("--t-bg")).toBe("#1C1620")
    expect(scope.style.getPropertyValue("--t-radius")).toBe("16px")
    // The app root keeps its own theme.
    await waitFor(() => expect(token("bg")).toBe("#F2F5F3"))
  })
})
