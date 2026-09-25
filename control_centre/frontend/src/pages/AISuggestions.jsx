import { PageHeader, SimBadge } from '../components/Layout.jsx'
import {
  IncidentPredictionCard,
  FleetDecisionCard,
  DemandPredictionCard,
} from '../components/V2IntelligencePanels.jsx'
import { DemandIntelPanel } from '../components/BackendOnlyPanels.jsx'

/**
 * AI Suggestions — dedicated operations page for fleet decision intelligence
 * and demand prediction. The AI keeps running in the background; this page is
 * the single place operators consume its suggestions:
 *
 *  - Deploy additional buses to routes (fleet decision intelligence)
 *  - Demand / overcrowding forecasts (demand prediction)
 *  - Predictive incident intelligence (which buses are trending toward trouble)
 *
 * Road Risk Corridors moved to the Road Intelligence page; the dashboard no
 * longer embeds any of these panels.
 */
export default function AISuggestions() {
  return (
    <>
      <PageHeader
        title="AI Suggestions · Operations"
        sub="Fleet decision intelligence · demand prediction · predictive incidents"
        right={<SimBadge />}
      />
      <div className="muted mb-16" style={{ fontSize: 12 }}>
        Rule-based AI runs continuously in the background. Suggestions below are computed
        from live fleet telemetry — rebalancing, extra bus deployment, crowding forecasts
        and risk escalations. Nothing here changes operations automatically; every action
        stays with the operator.
      </div>

      <IncidentPredictionCard />
      <FleetDecisionCard />
      <DemandPredictionCard />
      <DemandIntelPanel />
    </>
  )
}
