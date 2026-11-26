import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { deviceName } from "./sessions-section"

describe("Sessions", () => {
  it("lists where you are signed in and signs out every other session", async () => {
    const user = userEvent.setup()
    renderApp("/settings/security")
    const list = await screen.findByRole("list", { name: "Signed-in sessions" })
    expect(await within(list).findAllByRole("listitem")).toHaveLength(2)
    expect(within(list).getByText("This browser")).toBeInTheDocument()
    expect(within(list).getByText("Chrome on Android")).toBeInTheDocument()
    await user.click(
      screen.getByRole("button", { name: "Sign out everywhere else" })
    )
    expect(
      await screen.findByText(/Every other session is signed out/)
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(
        within(
          screen.getByRole("list", { name: "Signed-in sessions" })
        ).getAllByRole("listitem")
      ).toHaveLength(1)
    )
  })

  it("names a device from its user agent", () => {
    expect(deviceName(null)).toBe("Unknown device")
    expect(
      deviceName(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
      )
    ).toBe("Safari on macOS")
  })
})
