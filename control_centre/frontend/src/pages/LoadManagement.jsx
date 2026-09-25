import { useMemo } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'
import { StatusBadge } from '../components/UI.jsx'

function CabinOccupancyCell({ occ }) {
  if (!occ) return <span className="muted">—</span>
  if (occ.occupancy_count == null) return <span className="muted">{occ.status || 'no estimate'}</span>
  const pct = occ.occupancy_percentage
  const color = pct >= 90 ? 'var(--red)' : pct >= 75 ? 'var(--amber)' : '#17212B'
  return (
    <span className="mono" style={{ color }}>
      {pct}% ({occ.occupancy_count}/{occ.capacity}) · {occ.crowding_level}
    </span>
  )
}

function OccupancyCell({ occ, cabin }) {
  const passengers = occ?.passengers ?? 0
  const capacity = occ?.capacity ?? 60
  const pct = occ?.pct ?? 0
  const crowd = occ?.crowd_level || 'UNKNOWN'

  // Use cabin data if available
  const cabinCount = cabin?.occupancy_count
  const cabinPct = cabin?.occupancy_percentage
  const cabinCrowd = cabin?.crowding_level
  const cabinSource = cabin?.source

  const displayPct = cabinPct ?? pct
  const displayCrowd = cabinCrowd ?? crowd
  const displayCount = cabinCount ?? passengers

  const color = displayPct >= 90 ? 'var(--red)' : displayPct >= 75 ? 'var(--amber)' : '#17212B'
  const source = cabinSource || (occ?.source || 'UNKNOWN')

  return (
    <div>
      <div className="mono" style={{ fontSize: 13, fontWeight: 600, color }}>
        {displayCount}/{capacity}
      </div>
      <div className="flex align-center gap-4" style={{ fontSize: 11 }}>
        <span className="mono">{Math.round(displayPct)}%</span>
        <span className="chip" style={{
          fontSize: 9,
          padding: '1px 4px',
          background: displayCrowd === 'CRITICAL' ? '#fecaca' :
                     displayCrowd === 'HIGH' ? '#fed7aa' :
                     displayCrowd === 'MODERATE' ? '#fef3c7' : '#e0e7ff',
          color: displayCrowd === 'CRITICAL' ? '#991b1b' :
                 displayCrowd === 'HIGH' ? '#9a3412' :
                 displayCrowd === 'MODERATE' ? '#92400e' : '#1e40af',
        }}>
          {displayCrowd}
        </span>
      </div>
      <div style={{ fontSize: 10, color: '#6b7280', marginTop: 2 }}>{source}</div>
    </div>
  )
}

function CapacityPressureCell({ bus }) {
  const occ = bus.occupancy || {}
  const passengers = occ.passengers ?? 0
  const capacity = occ.capacity ?? 60
  const pct = occ.pct ?? 0

  // Simple pressure indicator based on current occupancy
  let pressure = 'NORMAL'
  let pressureColor = 'var(--green)'
  if (pct >= 95) {
    pressure = 'CRITICAL'
    pressureColor = 'var(--red)'
  } else if (pct >= 85) {
    pressure = 'HIGH'
    pressureColor = 'var(--amber)'
  } else if (pct >= 70) {
    pressure = 'WATCH'
    pressureColor = '#f59e0b'
  }

  return (
    <div>
      <div className="chip" style={{
        fontSize: 10,
        background: pressure === 'CRITICAL' ? '#fecaca' :
                   pressure === 'HIGH' ? '#fed7aa' :
                   pressure === 'WATCH' ? '#fef3c7' : '#dcfce7',
        color: pressure === 'CRITICAL' ? '#991b1b' :
               pressure === 'HIGH' ? '#9a3412' :
               pressure === 'WATCH' ? '#92400e' : '#166534',
      }}>
        {pressure}
      </div>
    </div>
  )
}

function DemandTrendCell({ bus }) {
  const hourly = bus.boarding_by_hour || {}
  const dailyTotal = bus.daily_boarding_total || 0
  const peakHour = bus.boarding_peak_hour

  if (!hourly || dailyTotal <= 0) {
    return <span className="muted">—</span>
  }

  // Simple trend: compare morning vs afternoon
  const morning = (parseInt(hourly['7'] || 0) + parseInt(hourly['8'] || 0) + parseInt(hourly['9'] || 0))
  const afternoon = (parseInt(hourly['16'] || 0) + parseInt(hourly['17'] || 0) + parseInt(hourly['18'] || 0))

  let trend = 'STABLE'
  let trendColor = '#6b7280'
  if (morning > afternoon * 1.3) {
    trend = 'PEAK'
    trendColor = 'var(--amber)'
  } else if (afternoon > morning * 1.3) {
    trend = 'EVENING'
    trendColor = 'var(--accent)'
  }

  return (
    <div>
      <div className="mono" style={{ fontSize: 12 }}>{dailyTotal} pax/day</div>
      <div style={{ fontSize: 10, color: trendColor }}>{trend}</div>
    </div>
  )
}

export default function LoadManagement() {
  const { data } = usePoll(api.buses, 4000)
  const buses = useMemo(() =>
    [...(data?.buses || [])].sort((a, b) => (b.load.load_pct || 0) - (a.load.load_pct || 0)),
    [data]
  )
  const showCabin = useMemo(() => buses.some((b) => b.cabin_occupancy), [buses])

  const stats = useMemo(() => {
    const total = buses.length
    const overloaded = buses.filter(b => (b.occupancy?.pct ?? 0) >= 95).length
    const nearCapacity = buses.filter(b => {
      const pct = b.occupancy?.pct ?? 0
      return pct >= 85 && pct < 95
    }).length
    const normal = total - overloaded - nearCapacity
    return { total, overloaded, nearCapacity, normal }
  }, [buses])

  return (
    <>
      <PageHeader
        title="Load Management"
        sub="Passenger load, demand intelligence & capacity awareness"
        right={<SimBadge />}
      />

      {/* Fleet load summary */}
      <div className="card mb-16">
        <div className="card-header">
          <h3 className="card-title">Fleet Load Summary</h3>
          <span className="chip" style={{ fontSize: 10, background: '#e0e7ff', color: '#2563eb' }}>HEURISTIC</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
          {[
            ['Total Buses', stats.total, '#17212B'],
            ['Over Capacity', stats.overloaded, stats.overloaded > 0 ? 'var(--red)' : '#17212B'],
            ['Near Capacity', stats.nearCapacity, stats.nearCapacity > 0 ? 'var(--amber)' : '#17212B'],
            ['Normal', stats.normal, 'var(--green)'],
          ].map(([label, value, color]) => (
            <div key={label}>
              <div className="muted" style={{ fontSize: 10, fontFamily: 'monospace', textTransform: 'uppercase' }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color, fontFamily: 'monospace' }}>{value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Main load table */}
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Bus Load Details</h3>
          <div className="flex gap-8">
            <span className="muted" style={{ fontSize: 11 }}>Sorted by load %</span>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Bus</th>
                <th>Route</th>
                <th>Passengers</th>
                <th>Occupancy</th>
                <th>Load (GVW)</th>
                <th>Load %</th>
                <th>Status</th>
                <th>Capacity Pressure</th>
                <th>Demand</th>
                {showCabin && <th>Cabin Camera</th>}
              </tr>
            </thead>
            <tbody>
              {buses.map((b) => {
                const occ = b.occupancy || {}
                return (
                  <tr key={b.bus_id}>
                    <td><strong>{b.bus_id}</strong></td>
                    <td className="muted">{b.route_code || b.route}</td>
                    <td>
                      <OccupancyCell occ={occ} cabin={b.cabin_occupancy} />
                    </td>
                    <td>
                      <div style={{ width: 100 }}>
                        <div className="flex justify-between" style={{ fontSize: 11 }}>
                          <span className="mono">{occ.pct ?? 0}%</span>
                        </div>
                        <div className="progress mt-8">
                          <div
                            style={{
                              width: `${Math.min(100, occ.pct ?? 0)}%`,
                              background: (occ.pct ?? 0) >= 95 ? 'var(--red)' :
                                         (occ.pct ?? 0) >= 85 ? 'var(--amber)' : 'var(--green)',
                            }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="mono">{b.load.gvw_kg.toLocaleString()} kg</td>
                    <td>
                      <div style={{ width: 80 }}>
                        <div className="flex justify-between" style={{ fontSize: 11 }}>
                          <span className="mono">{b.load.load_pct}%</span>
                        </div>
                        <div className="progress mt-8">
                          <div
                            style={{
                              width: `${Math.min(100, b.load.load_pct)}%`,
                              background: b.load.load_pct > 100 ? 'var(--red)' : b.load.load_pct > 90 ? 'var(--amber)' : 'var(--green)',
                            }}
                          />
                        </div>
                      </div>
                    </td>
                    <td><StatusBadge status={b.load.status} /></td>
                    <td><CapacityPressureCell bus={b} /></td>
                    <td><DemandTrendCell bus={b} /></td>
                    {showCabin && <td><CabinOccupancyCell occ={b.cabin_occupancy} /></td>}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
