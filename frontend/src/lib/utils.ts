import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

/** tailwind-merge, taught the project's extra type sizes so they don't clash with colours. */
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: ["2xs", "md"] },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
