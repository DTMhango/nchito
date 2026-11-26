/**
 * Colour-vision deficiency simulation (Machado, Oliveira and Fernandes 2009, severity 1; full
 * achromatopsia by luminance). Matrices act on linear RGB, which is also what an SVG
 * `feColorMatrix` uses by default, so the preview filter and the status check agree.
 */
import { oklabDistance, resolveColour, type RGBA } from "./colour"
import { tokenEnv } from "./contrast"
import { STATUS_TOKENS } from "./spec"

export type Deficiency =
  "protanopia" | "deuteranopia" | "tritanopia" | "achromatopsia"

type M3 = readonly [readonly number[], readonly number[], readonly number[]]

export const CVD_MATRICES: Record<Deficiency, M3> = {
  protanopia: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deuteranopia: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
  tritanopia: [
    [1.255528, -0.076749, -0.178779],
    [-0.078411, 0.930809, 0.147602],
    [0.004733, 0.691367, 0.3039],
  ],
  achromatopsia: [
    [0.2126, 0.7152, 0.0722],
    [0.2126, 0.7152, 0.0722],
    [0.2126, 0.7152, 0.0722],
  ],
}

export const DEFICIENCIES = Object.keys(CVD_MATRICES) as Deficiency[]

/** The 4x5 `values` string of an SVG feColorMatrix for a deficiency. */
export function feColorMatrixValues(d: Deficiency): string {
  return (
    CVD_MATRICES[d].map((row) => [...row, 0, 0].join(" ")).join(" ") +
    " 0 0 0 1 0"
  )
}

const toLinear = (c: number) =>
  c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
const fromLinear = (c: number) =>
  c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055
const clamp = (x: number) => Math.min(1, Math.max(0, x))

export function simulate(c: RGBA, d: Deficiency | null): RGBA {
  if (!d) return c
  const lin = [toLinear(c[0]), toLinear(c[1]), toLinear(c[2])]
  const m = CVD_MATRICES[d]
  const out = m.map((row) =>
    clamp(
      fromLinear(clamp(row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2]))
    )
  )
  return [out[0], out[1], out[2], c[3]]
}

export type StatusClash = {
  deficiency: Deficiency | null
  a: string
  b: string
  distance: number
}

/**
 * Status colours (good, warn, danger, info) closer than `minDistance` (OKLab) to each other, in
 * normal vision and under each simulated dichromacy. Achromatopsia is left out: with no hue at
 * all, status reads from its label and icon, which every status chip carries. Empty means the
 * colours stay distinguishable.
 */
export function statusClashes(
  tokens: Record<string, string>,
  minDistance: number
): StatusClash[] {
  const env = tokenEnv(tokens)
  const colours: [string, RGBA][] = []
  for (const name of STATUS_TOKENS) {
    try {
      colours.push([name, resolveColour(env[name], env)])
    } catch {
      /* invalid values are reported by the validator */
    }
  }
  const out: StatusClash[] = []
  for (const d of [
    null,
    ...DEFICIENCIES.filter((x) => x !== "achromatopsia"),
  ]) {
    for (let i = 0; i < colours.length; i++)
      for (let j = i + 1; j < colours.length; j++) {
        const distance = oklabDistance(
          simulate(colours[i][1], d),
          simulate(colours[j][1], d)
        )
        if (distance < minDistance)
          out.push({
            deficiency: d,
            a: colours[i][0],
            b: colours[j][0],
            distance: Math.round(distance * 1000) / 1000,
          })
      }
  }
  return out
}
