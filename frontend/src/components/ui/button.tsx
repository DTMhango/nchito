import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border border-transparent bg-clip-padding text-[0.9rem] font-semibold whitespace-nowrap transition-[background-color,border-color,color,filter,transform] outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-ink active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-[15px]",
  {
    variants: {
      variant: {
        default:
          "border-primary bg-primary text-primary-foreground hover:brightness-[1.07]",
        outline:
          "border-border bg-surface text-foreground hover:border-border-strong hover:bg-surface-2 aria-expanded:border-border-strong aria-expanded:bg-surface-2",
        secondary: "bg-sunken text-foreground hover:bg-surface-2",
        ghost:
          "text-muted-foreground hover:bg-sunken hover:text-foreground aria-expanded:bg-sunken aria-expanded:text-foreground",
        destructive: "bg-danger-soft text-danger hover:brightness-[0.97]",
        link: "text-primary-ink underline-offset-4 hover:underline",
      },
      size: {
        default: "h-8 px-3",
        xs: "h-6 gap-1 px-2 text-xs",
        sm: "h-7 gap-1 px-2.5 text-sm",
        lg: "h-9 px-4",
        icon: "size-[34px]",
        "icon-xs": "size-6",
        "icon-sm": "size-7",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
