import { useState } from "react"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { KanbanBoard } from "./kanban-board"

type Item = { id: string; name: string; col: string }
const COLUMNS = [
  { id: "short", title: "Shortlisted" },
  { id: "ready", title: "Ready to apply" },
  { id: "applied", title: "Applied" },
]

function Board({ onMove }: { onMove?: (id: string, to: string) => void }) {
  const [items, setItems] = useState<Item[]>([
    { id: "a", name: "Kafue Analytics", col: "short" },
    { id: "b", name: "Sample Re", col: "short" },
  ])
  return (
    <KanbanBoard
      columns={COLUMNS}
      items={items}
      getId={(i) => i.id}
      getColumn={(i) => i.col}
      getLabel={(i) => i.name}
      renderCard={(i) => <span>{i.name}</span>}
      onMove={(id, to) => {
        onMove?.(id, to)
        setItems((xs) => xs.map((x) => (x.id === id ? { ...x, col: to } : x)))
      }}
    />
  )
}

const column = (title: string) =>
  screen.getByRole("listitem", { name: new RegExp(`^${title}`) })

describe("KanbanBoard keyboard", () => {
  it("moves a focused card one column right and left with the arrow keys", async () => {
    const user = userEvent.setup()
    const onMove = vi.fn()
    render(<Board onMove={onMove} />)

    const card = screen.getByRole("button", { name: "Kafue Analytics" })
    card.focus()
    await user.keyboard("{ArrowRight}")
    expect(onMove).toHaveBeenCalledWith("a", "ready")
    expect(
      within(column("Ready to apply")).getByText("Kafue Analytics")
    ).toBeInTheDocument()
    expect(
      screen.getByText("Moved Kafue Analytics to Ready to apply.")
    ).toBeInTheDocument()
    // Focus stays on the moved card so moves can be chained.
    expect(
      screen.getByRole("button", { name: "Kafue Analytics" })
    ).toHaveFocus()

    await user.keyboard("{ArrowRight}")
    expect(
      within(column("Applied")).getByText("Kafue Analytics")
    ).toBeInTheDocument()

    await user.keyboard("{ArrowLeft}")
    expect(onMove).toHaveBeenLastCalledWith("a", "ready")
  })

  it("does nothing past the first or last column", async () => {
    const user = userEvent.setup()
    const onMove = vi.fn()
    render(<Board onMove={onMove} />)
    screen.getByRole("button", { name: "Sample Re" }).focus()
    await user.keyboard("{ArrowLeft}")
    expect(onMove).not.toHaveBeenCalled()
  })

  it("moves focus between cards in a column with up and down", async () => {
    const user = userEvent.setup()
    render(<Board />)
    screen.getByRole("button", { name: "Kafue Analytics" }).focus()
    await user.keyboard("{ArrowDown}")
    expect(screen.getByRole("button", { name: "Sample Re" })).toHaveFocus()
  })

  it("labels each column with its card count", () => {
    render(<Board />)
    expect(column("Shortlisted")).toHaveAccessibleName("Shortlisted, 2 cards")
    expect(column("Applied")).toHaveAccessibleName("Applied, 0 cards")
  })
})
