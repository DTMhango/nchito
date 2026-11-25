import type { ReactNode } from "react"
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query"
import { MotionConfig } from "motion/react"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Toaster } from "@/components/ui/sonner"
import { ThemeProvider, useTheme } from "@/themes/provider"

function MotionPrefs({ children }: { children: ReactNode }) {
  const { appearance } = useTheme()
  return (
    <MotionConfig reducedMotion={appearance.reduced_motion ? "always" : "user"}>
      {children}
    </MotionConfig>
  )
}

/** Every app-wide provider, in one place, so tests can render the same tree. */
export function AppProviders({
  queryClient,
  children,
}: {
  queryClient: QueryClient
  children: ReactNode
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MotionPrefs>
          <TooltipProvider delayDuration={300}>
            {children}
            <Toaster />
          </TooltipProvider>
        </MotionPrefs>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
