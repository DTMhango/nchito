/// <reference types="vitest/config" />
import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { VitePWA } from "vite-plugin-pwa"

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // `vite --mode mock` (npm run dev:mock) runs against the MSW mock backend.
  if (mode === "mock") process.env.VITE_MOCK = "1"
  return {
    plugins: [
      react(),
      tailwindcss(),
      VitePWA({
        registerType: "autoUpdate",
        injectRegister: "auto",
        includeAssets: ["icon.svg", "apple-touch-icon.png"],
        manifest: {
          name: "Nchito",
          short_name: "Nchito",
          description: "A private job-hunting cockpit.",
          start_url: "/today",
          scope: "/",
          display: "standalone",
          // Copperbelt light ground and primary; the app repaints in the owner's theme once open.
          background_color: "#F2F5F3",
          theme_color: "#0F6B55",
          icons: [
            { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
            { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
            {
              src: "/icon-maskable-512.png",
              sizes: "512x512",
              type: "image/png",
              purpose: "maskable",
            },
            { src: "/icon.svg", sizes: "any", type: "image/svg+xml" },
          ],
        },
        workbox: {
          navigateFallback: "/index.html",
          navigateFallbackDenylist: [/^\/api\//, /^\/mcp/],
          globIgnores: ["**/mockServiceWorker.js"],
          maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        },
      }),
    ],
    resolve: {
      alias: {
        "@": resolve(import.meta.dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": { target: "http://localhost:8000", changeOrigin: true },
      },
    },
    test: {
      environment: "jsdom",
      globals: false,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
      include: ["src/**/*.test.{ts,tsx}"],
      restoreMocks: true,
    },
  }
})
