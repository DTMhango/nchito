import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { renderApp } from "@/test/render"

describe("command palette", () => {
  it("opens with Ctrl K and navigates to a screen", async () => {
    const user = userEvent.setup()
    const { router } = renderApp("/today")
    await screen.findByRole("heading", { level: 1, name: "Today" })

    await user.keyboard("{Control>}k{/Control}")
    const input = await screen.findByPlaceholderText(
      "Search screens and commands"
    )
    await user.type(input, "Applications")
    await user.keyboard("{Enter}")

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/applications")
    )
    expect(
      screen.queryByPlaceholderText("Search screens and commands")
    ).not.toBeInTheDocument()
  })

  it("switches theme from the palette", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    await screen.findByRole("heading", { level: 1, name: "Today" })
    await user.click(
      screen.getByRole("button", { name: "Search and commands" })
    )
    await user.type(await screen.findByRole("combobox"), "Theme: Paper")
    await user.keyboard("{Enter}")
    await waitFor(() =>
      expect(document.documentElement.dataset.themeId).toBe("paper")
    )
  })
})
