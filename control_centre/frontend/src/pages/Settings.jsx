import { useState } from 'react'
import { api, usePoll } from '../api.js'
import { PageHeader, SimBadge } from '../components/Layout.jsx'

function Field({ label, value, onChange, unit, step }) {
  return (
    <tr>
      <td>{label}</td>
      <td>
        <input
          type="number"
          step={step || 'any'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="config-input"
        />
        {unit && <span className="muted mono" style={{ marginLeft: 6 }}>{unit}</span>}
      </td>
    </tr>
  )
}

export default function Settings() {
  const { data } = usePoll(api.settings, 10000)
  const [bus, setBus] = useState(null)
  const [detection, setDetection] = useState(null)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')

  // keep local editable copies in sync with fetched data
  const mergedBus = bus || data?.bus
  const mergedDet = detection || data?.detection

  const setBusVal = (key, v) => setBus((cur) => ({ ...(data?.bus || {}), ...(cur || {}), [key]: parseFloat(v) }))
  const setDetVal = (key, v) => setDetection((cur) => ({ ...(data?.detection || {}), ...(cur || {}), [key]: parseFloat(v) }))

  async function save() {
    setSaving(true)
    setSavedMsg('')
    try {
      await api.updateSettings({ bus: bus || data.bus, detection: detection || data.detection })
      setBus(null); setDetection(null)
      setSavedMsg('✓ Settings saved')
    } catch (e) {
      setSavedMsg('✗ Save failed: ' + String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Settings"
        sub="Platform configuration · editable"
        right={<SimBadge />}
      />
      {!data && <div className="empty">Loading…</div>}
      {data && (
        <div className="grid grid-2">
          <div className="card">
            <div className="card-header"><h3 className="card-title">System</h3></div>
            <table className="table">
              <tbody>
                <tr><td>Demo mode</td><td><span className="badge badge-indigo">ON — demo data</span></td></tr>
                <tr><td>City</td><td>{data.city?.name} ({data.city?.country})</td></tr>
                <tr><td>Map centre</td><td className="mono">{data.city?.map_center?.join(', ')}</td></tr>
                <tr><td>Data source</td><td className="muted">estimated fleet; real bus-node link planned</td></tr>
                <tr><td>Backend</td><td className="mono">Flask REST API</td></tr>
              </tbody>
            </table>
          </div>

          <div className="card">
            <div className="card-header"><h3 className="card-title">Bus / Load Assumptions</h3></div>
            <table className="table">
              <tbody>
                <Field label="Tare weight (kg)" value={mergedBus?.tare_weight_kg ?? ''} onChange={(v) => setBusVal('tare_weight_kg', v)} />
                <Field label="Max GVW (kg)" value={mergedBus?.max_gvw_kg ?? ''} onChange={(v) => setBusVal('max_gvw_kg', v)} />
                <Field label="Payload limit (kg)" value={mergedBus?.payload_limit_kg ?? ''} onChange={(v) => setBusVal('payload_limit_kg', v)} />
                <Field label="Tyre target (PSI)" value={mergedBus?.tyre_target_psi ?? ''} onChange={(v) => setBusVal('tyre_target_psi', v)} />
              </tbody>
            </table>
          </div>

          <div className="card">
            <div className="card-header"><h3 className="card-title">Detection Thresholds</h3></div>
            <table className="table">
              <tbody>
                <Field label="EAR threshold" value={mergedDet?.ear_threshold ?? ''} onChange={(v) => setDetVal('ear_threshold', v)} />
                <Field label="MAR threshold" value={mergedDet?.mar_threshold ?? ''} onChange={(v) => setDetVal('mar_threshold', v)} />
                <Field label="Eye-closed duration (s)" value={mergedDet?.eye_closed_duration ?? ''} onChange={(v) => setDetVal('eye_closed_duration', v)} />
              </tbody>
            </table>
          </div>

          <div className="card">
            <div className="card-header"><h3 className="card-title">Prototype Status</h3></div>
            <div className="chip mb-8">IMPLEMENTED: driver monitoring (bus node) · dashboard UI</div>
            <div className="chip mb-8">PROTOTYPE: multi-camera · GPS · IMU · load · siren (estimated)</div>
            <div className="chip mb-8">PROPOSED/FUTURE: cabin AI · road AI · event fusion</div>
            <div className="mt-8">
              <button className="btn btn-primary" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save Configuration'}
              </button>
              {savedMsg && <span className="muted" style={{ marginLeft: 8 }}>{savedMsg}</span>}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
