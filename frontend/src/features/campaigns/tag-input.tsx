import { useState } from "react"
import { X } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

/** A list of short strings: type and press Enter (or Add); remove with the x. */
export function TagInput({
  values,
  onChange,
  label,
  placeholder,
}: {
  values: string[]
  onChange: (next: string[]) => void
  label: string
  placeholder?: string
}) {
  const [text, setText] = useState("")
  const add = () => {
    const v = text.trim()
    if (!v || values.some((x) => x.toLowerCase() === v.toLowerCase())) {
      setText("")
      return
    }
    onChange([...values, v])
    setText("")
  }
  return (
    <div className="grid gap-2">
      {values.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={label}>
          {values.map((v) => (
            <li
              key={v}
              className="inline-flex items-center gap-1 rounded-full bg-sunken py-0.5 pr-1 pl-2.5 text-sm"
            >
              {v}
              <button
                type="button"
                aria-label={`Remove ${v}`}
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="grid size-5 place-items-center rounded-full text-muted-foreground hover:bg-surface-2 hover:text-foreground"
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <Input
          aria-label={`Add to ${label}`}
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              add()
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add}>
          Add
        </Button>
      </div>
    </div>
  )
}
