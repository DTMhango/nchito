import { Toaster as Sonner, type ToasterProps } from "sonner"
import {
  CircleCheckIcon,
  InfoIcon,
  TriangleAlertIcon,
  OctagonXIcon,
  Loader2Icon,
} from "lucide-react"
import { useOptionalTheme } from "@/themes/provider"

/** Toasts follow the app's resolved mode and use theme tokens (mockup: inverted chip). */
const Toaster = ({ ...props }: ToasterProps) => {
  const mode = useOptionalTheme()?.mode ?? "light"

  return (
    <Sonner
      theme={mode}
      className="toaster group"
      position="bottom-right"
      offset={{ bottom: 18, right: 16 }}
      mobileOffset={{ bottom: 72, right: 16, left: 16 }}
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--t-text)",
          "--normal-text": "var(--t-bg)",
          "--normal-border": "var(--t-text)",
          "--border-radius": "var(--t-radius)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "cn-toast font-sans text-[0.9rem]",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
