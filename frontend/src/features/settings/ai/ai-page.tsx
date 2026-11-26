import { Separator } from "@/components/ui/separator"
import { BudgetSection, SpendSection } from "./budget-section"
import { PricesSection } from "./prices-section"
import { PromptsSection } from "./prompts-section"
import { ProvidersSection } from "./providers-section"
import { RoutingSection } from "./routing-section"

/**
 * Settings, AI (DESIGN 11): providers, model per stage, budget and spend, price table, prompts.
 * Nothing paid runs until a monthly cap is set.
 */
export function AiSettingsPage() {
  return (
    <div className="grid gap-7">
      <SpendSection />
      <BudgetSection />
      <Separator />
      <ProvidersSection />
      <RoutingSection />
      <Separator />
      <PricesSection />
      <Separator />
      <PromptsSection />
    </div>
  )
}
