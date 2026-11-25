import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { db } from "@/mocks/db"
import { renderApp } from "@/test/render"
import { safeRedirect } from "./guard"

describe("route guard", () => {
  it("sends a visitor with no owner to first-run setup", async () => {
    db.reset("fresh")
    const { router } = renderApp("/matches")
    await waitFor(() => expect(router.state.location.pathname).toBe("/setup"))
    expect(
      await screen.findByRole("heading", { name: "Set up your account" })
    ).toBeInTheDocument()
  })

  it("sends a signed-out owner to sign-in, remembering where they were going", async () => {
    db.reset("signed-out")
    const { router } = renderApp("/kit/guardrails")
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"))
    expect(router.state.location.search).toMatchObject({
      redirect: "/kit/guardrails",
    })
  })

  it("signs in and returns to the page asked for", async () => {
    db.reset("signed-out")
    const user = userEvent.setup()
    const { router } = renderApp("/campaigns")
    await screen.findByRole("heading", { name: "Sign in" })
    await user.type(screen.getByLabelText("Email"), "owner@example.com")
    await user.type(screen.getByLabelText("Password"), "demo-password")
    await user.click(screen.getByRole("button", { name: "Sign in" }))
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/campaigns")
    )
  })

  it("shows the server's message on a wrong password", async () => {
    db.reset("signed-out")
    const user = userEvent.setup()
    renderApp("/today")
    await screen.findByRole("heading", { name: "Sign in" })
    await user.type(screen.getByLabelText("Email"), "owner@example.com")
    await user.type(screen.getByLabelText("Password"), "wrong")
    await user.click(screen.getByRole("button", { name: "Sign in" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("don't match")
  })

  it("lets a signed-in owner through, and keeps them off setup and sign-in", async () => {
    const { router } = renderApp("/today")
    expect(
      await screen.findByRole("heading", { level: 1, name: "Today" })
    ).toBeInTheDocument()
    await router.navigate({ to: "/sign-in" })
    await waitFor(() => expect(router.state.location.pathname).toBe("/today"))
    await router.navigate({ to: "/setup" })
    await waitFor(() =>
      expect(router.state.location.pathname).not.toBe("/setup")
    )
  })

  it("only follows same-app redirects", () => {
    expect(safeRedirect("/matches")).toBe("/matches")
    expect(safeRedirect("https://evil.example")).toBe("/today")
    expect(safeRedirect("//evil.example")).toBe("/today")
    expect(safeRedirect(undefined)).toBe("/today")
  })
})
