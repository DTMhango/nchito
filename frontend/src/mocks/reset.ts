/** Reset every mock store to its seed (each test starts from the same fictional dataset). */
import { resetAiMock } from "./handlers/ai"
import { resetApplicationsMock } from "./handlers/applications"
import { resetCampaignMocks } from "./handlers/campaigns"
import { resetJobsMock } from "./handlers/jobs"
import { resetKitMock } from "./handlers/kit"
import { resetMatchesMock } from "./handlers/matches"
import { resetSettingsMock } from "./handlers/settings"
import { resetSourcesMock } from "./data/sources"

export function resetAllMocks() {
  resetSettingsMock()
  resetAiMock()
  resetMatchesMock()
  resetCampaignMocks()
  resetApplicationsMock()
  resetJobsMock()
  resetKitMock()
  resetSourcesMock()
}
