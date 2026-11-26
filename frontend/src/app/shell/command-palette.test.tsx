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

  it("reaches every wave 4 screen", async () => {
    const user = userEvent.setup()
    renderApp("/today")
    await screen.findByRole("heading", { level: 1, name: "Today" })
    await user.keyboard("{Control>}k{/Control}")
    await screen.findByPlaceholderText("Search screens and commands")
    for (const name of [
      "Insights",
      "Employers",
      "Follow-ups",
      "Wind down",
      "Theme studio",
      "Upcoming interviews and deadlines",
      "Mock interview",
      "Settings: Insights",
      "Settings: Follow-ups and wind-down",
    ])
      expect(
        screen.getByRole("option", { name: new RegExp(`^${name}`) })
      ).toBeInTheDocument()
  })

  it("opens Today at upcoming interviews", async () => {
    const user = userEvent.setup()
    const { router } = renderApp("/applications")
    await screen.findByRole("heading", { level: 1, name: "Applications" })
    await user.keyboard("{Control>}k{/Control}")
    await user.type(
      await screen.findByPlaceholderText("Search screens and commands"),
      "Mock interview"
    )
    await user.keyboard("{Enter}")
    await waitFor(() =>
      expect(router.state.location.search).toMatchObject({ show: "upcoming" })
    )
    expect(
      await screen.findByRole("heading", { name: "Upcoming interviews" })
    ).toBeInTheDocument()
  })
})
