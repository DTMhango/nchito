#!/usr/bin/env node
// No literal colours outside src/themes/ (DESIGN 10.4). Components use tokens only.
//
// Flags, in .ts/.tsx/.css/.js files under src/:
//   - hex colours (#abc, #aabbcc, #aabbccdd)
//   - colour functions: rgb(), rgba(), hsl(), hsla(), hwb(), lab(), lch(), oklab(), oklch(), color()
//   - Tailwind palette classes (bg-red-500, text-white, border-black/20, ...)
//
// A line may opt out with a comment containing `colour-lint-ignore: <reason>`
// on the same line or the line above. Use it only for things that are not colours
// we paint, such as attribute selectors matching a library's defaults.
import { readFileSync, readdirSync, statSync } from "node:fs"
import { join, relative, sep } from "node:path"

const ROOT = "src"
const ALLOWED_DIRS = [join("src", "themes") + sep]
const EXT = /\.(tsx?|css|m?js)$/

const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
const UTIL =
  "bg|text|border|border-[trblxy]|ring|ring-offset|fill|stroke|from|via|to|outline|shadow|decoration|accent|caret|divide|placeholder"

const RULES = [
  {
    name: "hex colour",
    re: /(?<![\w&/-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g,
  },
  {
    name: "colour function",
    re: /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/g,
  },
  {
    name: "Tailwind palette class",
    re: new RegExp(
      `(?<![\\w-])(?:[\\w-]+:)*(?:${UTIL})-(?:(?:${PALETTE})-\\d{2,3}|white|black)(?:\\/\\d+)?(?![\\w-])`,
      "g"
    ),
  },
]

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (EXT.test(name)) out.push(p)
  }
  return out
}

const files = walk(ROOT).filter(
  (f) => !ALLOWED_DIRS.some((d) => (f + sep).startsWith(d) || f.startsWith(d))
)
const problems = []
for (const file of files) {
  const lines = readFileSync(file, "utf8").split(/\r?\n/)
  lines.forEach((line, i) => {
    if (
      /colour-lint-ignore:\s*\S/.test(line) ||
      /colour-lint-ignore:\s*\S/.test(lines[i - 1] ?? "")
    )
      return
    for (const rule of RULES) {
      rule.re.lastIndex = 0
      let m
      while ((m = rule.re.exec(line))) {
        problems.push(
          `${relative(".", file)}:${i + 1}:${m.index + 1}  ${rule.name} "${m[0]}"`
        )
      }
    }
  })
}

if (problems.length) {
  console.error(
    "Literal colours found outside src/themes/. Use theme tokens instead:\n"
  )
  for (const p of problems) console.error("  " + p)
  console.error(`\n${problems.length} problem(s).`)
  process.exit(1)
}
console.log(`No literal colours in ${files.length} files outside src/themes/.`)
