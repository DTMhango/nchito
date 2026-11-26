import { Link } from "@tanstack/react-router"
import { History } from "lucide-react"
import { PageHeader } from "@/components/page-header"
import { View } from "@/components/view"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { EmployersPanel } from "./employers-panel"
import { SchedulesPanel } from "./schedules-panel"
import { SourceList } from "./source-list"

/** Sources: the connector registry with health, watched employers and schedules (DESIGN 6, 10.3). */
export function SourcesPage() {
  return (
    <View>
      <PageHeader
        title="Sources"
        description="Where roles come from. One failing source never stops a sweep."
        actions={
          <Button asChild variant="outline">
            <Link to="/autopilot/runs">
              <History aria-hidden="true" />
              Run history
            </Link>
          </Button>
        }
      />
      <Tabs defaultValue="sources">
        <TabsList className="mb-4">
          <TabsTrigger value="sources">Sources</TabsTrigger>
          <TabsTrigger value="employers">Watched employers</TabsTrigger>
          <TabsTrigger value="schedules">Schedules</TabsTrigger>
        </TabsList>
        <TabsContent value="sources">
          <SourceList />
        </TabsContent>
        <TabsContent value="employers">
          <EmployersPanel />
        </TabsContent>
        <TabsContent value="schedules">
          <SchedulesPanel />
        </TabsContent>
      </Tabs>
    </View>
  )
}
