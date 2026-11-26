/** Reset every mock store to its seed (each test starts from the same fictional dataset). */
import { resetAiMock } from "./handlers/ai"
import { resetAutopilotMock } from "./handlers/autopilot"
import { resetRunnersMock } from "./handlers/runners"
import { resetApplicationsMock } from "./handlers/applications"
import { resetDataMock } from "./handlers/data"
import { resetCampaignMocks } from "./handlers/campaigns"
import { resetJobsMock } from "./handlers/jobs"
import { resetKitMock } from "./handlers/kit"
import { resetMatchesMock } from "./handlers/matches"
import { resetSettingsMock } from "./handlers/settings"
import { resetSourcesMock } from "./dataset/sources"
import { resetStudioMock } from "./handlers/studio"

export function resetAllMocks() {
  resetSettingsMock()
  resetAiMock()
  resetMatchesMock()
  resetCampaignMocks()
  resetApplicationsMock()
  resetAutopilotMock()
  resetRunnersMock()
  resetJobsMock()
  resetKitMock()
  resetSourcesMock()
  // After the Kit, Matches and Applications: the Studio seed reads all three.
  resetStudioMock()
  resetDataMock()
}
