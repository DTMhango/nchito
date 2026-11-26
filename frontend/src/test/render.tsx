import { render } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AppProviders } from "@/app/providers"
import { createAppRouter } from "@/app/router"
import { ThemeProvider } from "@/themes/provider"

export function testQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  })
}

/** Render the whole app at a path, with the mock backend. */
export function renderApp(path = "/today") {
  const queryClient = testQueryClient()
  const history = createMemoryHistory({ initialEntries: [path] })
  const router = createAppRouter(queryClient, history)
  const utils = render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  )
  return { ...utils, router, queryClient }
}

/** Render a subtree with query + theme providers only (no router). */
export function renderWithTheme(
  ui: ReactNode,
  queryClient = testQueryClient()
) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{ui}</ThemeProvider>
      </QueryClientProvider>
    ),
  }
}

/**
 * A user-event instance for form-filling tests. `delay: null` drops the macrotask user-event
 * otherwise waits between keystrokes; each keystroke still runs in act() and re-renders. A
 * test typing ~80 characters into a whole-app render spends ~40% less time, which keeps it
 * well inside the test timeout when the full suite runs on every core.
 */
export function setupUser() {
  return userEvent.setup({ delay: null })
}
