import { useQuery } from "@tanstack/react-query"
import { History, ListChecks } from "lucide-react"
import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CountBadge } from "@/components/chip"
import { View } from "@/components/view"
import { approvalQueueQuery, pendingQuery } from "./api"
import { ChannelsPanel } from "./channels-panel"
import { DispatchPanel } from "./dispatch-panel"
import { MasterPause } from "./master-pause"
import { PendingPanel } from "./pending-panel"
import { PolicyEditor } from "./policy-editor"
import { TrustedSitesPanel } from "./trusted-sites-panel"

/**
 * Autopilot: what the system may do on its own (DESIGN 8.1, 10.3, 18). Policy and limits,
 * what each channel enforces, sending and reconciliation, what is waiting on the owner and
 * trusted sites. Approvals have their own screen. Run history and schedules (wave 1) are linked.
 */
export function AutopilotPage() {
  const queue = useQuery(approvalQueueQuery())
  const pending = useQuery(pendingQuery())
  return (
    <View className="grid content-start gap-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button asChild variant="outline" size="sm">
          <Link to="/approvals">
            <ListChecks aria-hidden="true" />
            Approvals
            {queue.data && queue.data.length > 0 && (
              <CountBadge>{queue.data.length}</CountBadge>
            )}
          </Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link to="/autopilot/runs">
            <History aria-hidden="true" />
            Run history
          </Link>
        </Button>
      </div>
      <MasterPause />
      <Tabs defaultValue="policy">
        <TabsList className="max-w-full flex-wrap" aria-label="Autopilot">
          <TabsTrigger value="policy">Policy and limits</TabsTrigger>
          <TabsTrigger value="channels">Channels</TabsTrigger>
          <TabsTrigger value="sending">Sending</TabsTrigger>
          <TabsTrigger value="waiting">
            Waiting on you
            {pending.data && pending.data.length > 0 && (
              <CountBadge className="ml-1.5">{pending.data.length}</CountBadge>
            )}
          </TabsTrigger>
          <TabsTrigger value="trusted">Trusted sites</TabsTrigger>
        </TabsList>
        <TabsContent value="policy" className="pt-3">
          <PolicyEditor />
        </TabsContent>
        <TabsContent value="channels" className="pt-3">
          <ChannelsPanel />
        </TabsContent>
        <TabsContent value="sending" className="pt-3">
          <DispatchPanel />
        </TabsContent>
        <TabsContent value="waiting" className="pt-3">
          <PendingPanel />
        </TabsContent>
        <TabsContent value="trusted" className="pt-3">
          <TrustedSitesPanel />
        </TabsContent>
      </Tabs>
    </View>
  )
}
