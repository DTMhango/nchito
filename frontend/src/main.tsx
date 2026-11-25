import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "@tanstack/react-router"
import "./index.css"
import { bootTheme } from "@/themes/provider"
import { AppProviders } from "@/app/providers"
import { createAppRouter, createQueryClient } from "@/app/router"

// Paint in the cached (or default) theme before React renders anything.
bootTheme()

async function start() {
  if (import.meta.env.VITE_MOCK === "1") {
    const { startMockBackend } = await import("@/mocks/browser")
    await startMockBackend()
  }
  const queryClient = createQueryClient()
  const router = createAppRouter(queryClient)
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AppProviders queryClient={queryClient}>
        <RouterProvider router={router} />
      </AppProviders>
    </StrictMode>
  )
}

void start()
