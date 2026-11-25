import {
  Link,
  useRouter,
  type ErrorComponentProps,
} from "@tanstack/react-router"
import { CloudOff, MapPinOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/empty-state"
import { isApiError } from "@/lib/api/client"

/** Shown when a route's loader or guard throws, e.g. the API is unreachable. */
export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const offline = !isApiError(error) && error instanceof TypeError
  return (
    <div className="grid min-h-[60dvh] place-items-center px-4">
      <EmptyState
        icon={CloudOff}
        title={offline ? "Can't reach the server" : "Something went wrong"}
        description={
          offline
            ? "The app couldn't talk to its backend. Check it is running, then try again. In development, start it with VITE_MOCK=1 to use the built-in mock backend."
            : (error as Error).message
        }
        actions={
          <Button
            onClick={() => {
              reset()
              void router.invalidate()
            }}
          >
            Try again
          </Button>
        }
      />
    </div>
  )
}

export function RouteNotFound() {
  return (
    <div className="grid min-h-[60dvh] place-items-center px-4">
      <EmptyState
        icon={MapPinOff}
        title="This page doesn't exist"
        description="The link may be old or mistyped."
        actions={
          <Button asChild>
            <Link to="/today">Go to Today</Link>
          </Button>
        }
      />
    </div>
  )
}

export function RoutePending() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="grid min-h-[40dvh] place-items-center text-sm text-faint"
    >
      Loading…
    </div>
  )
}
