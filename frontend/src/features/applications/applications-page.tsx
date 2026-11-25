import { useState } from "react"
import { Columns3, Table2 } from "lucide-react"
import { DataTable, type Column } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
import { KanbanBoard, type KanbanColumn } from "@/components/kanban-board"
import { Segmented } from "@/components/segmented"
import { StagePill, type Stage } from "@/components/stage-pill"
import { View } from "@/components/view"

/** Board columns group the stages (DESIGN 4); end states share Closed. */
export const BOARD_COLUMNS: KanbanColumn[] = [
  { id: "shortlisted", title: "Shortlisted" },
  { id: "tailoring", title: "Tailoring" },
  { id: "ready", title: "Ready to apply" },
  { id: "submitted", title: "Applied" },
  { id: "interview", title: "Interview" },
  { id: "closed", title: "Closed" },
]

type AppRow = {
  id: string
  employer: string
  role: string
  stage: Stage
  next: string
}

const COLUMNS: Column<AppRow>[] = [
  {
    id: "employer",
    header: "Company",
    cell: (r) => <span className="font-semibold">{r.employer}</span>,
    sortValue: (r) => r.employer,
  },
  { id: "role", header: "Role", cell: (r) => r.role, sortValue: (r) => r.role },
  { id: "stage", header: "Stage", cell: (r) => <StagePill stage={r.stage} /> },
  {
    id: "next",
    header: "Next step",
    cell: (r) => <span className="text-muted-foreground">{r.next}</span>,
    hideBelow: "md",
  },
]

/** Applications: board and table of every role you are pursuing (DESIGN 10.3). */
export function ApplicationsPage() {
  const [layout, setLayout] = useState<"board" | "table">("board")
  const rows: AppRow[] = []

  return (
    <View>
      <div className="mb-4 flex flex-wrap items-center gap-2.5 pr-1">
        <Segmented
          aria-label="Layout"
          value={layout}
          onValueChange={setLayout}
          options={[
            { value: "board", label: "Board", icon: Columns3 },
            { value: "table", label: "Table", icon: Table2 },
          ]}
        />
        <span className="text-[0.9rem] text-muted-foreground">
          0 active · nothing needs a step
        </span>
        <span className="ml-auto text-[0.84rem] text-faint max-md:hidden">
          Drag cards between stages, or focus a card and use the arrow keys
        </span>
      </div>

      {layout === "board" ? (
        <KanbanBoard<AppRow>
          columns={BOARD_COLUMNS}
          items={rows}
          getId={(r) => r.id}
          getColumn={(r) => r.stage}
          getLabel={(r) => `${r.employer}, ${r.role}`}
          renderCard={() => null}
          onMove={() => {}}
          emptyColumn={(c) => (
            <p className="rounded-sm border border-dashed border-border-strong px-3 py-4 text-center text-sm text-faint">
              {c.id === "shortlisted"
                ? "Shortlist a role from Matches and it starts here."
                : "No roles at this stage."}
            </p>
          )}
        />
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={rows}
          getRowId={(r) => r.id}
          caption="Applications"
          empty={
            <EmptyState
              title="No applications yet"
              description="Every role you shortlist, tailor or apply to is listed here with its stage and next step."
            />
          }
        />
      )}
    </View>
  )
}
