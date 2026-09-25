import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import { PageHeader } from '../components/Layout.jsx'

const ROLE_LABELS = { operator: 'Operator', supervisor: 'Supervisor', admin: 'Admin' }
const ROLES = ['operator', 'supervisor', 'admin']

export default function Users() {
  const [users, setUsers] = useState([])
  const [loadErr, setLoadErr] = useState('')
  const [busy, setBusy] = useState(false)

  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'operator' })
  const [msg, setMsg] = useState('')
  const [msgErr, setMsgErr] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await api.listUsers()
      setUsers(data.users || [])
      setLoadErr('')
    } catch (e) {
      setLoadErr(String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])

  function show(m, isErr = false) {
    setMsg(m); setMsgErr(isErr)
    setTimeout(() => setMsg(''), 4000)
  }

  async function createUser(e) {
    e.preventDefault()
    setBusy(true)
    try {
      await api.createUser(newUser)
      setNewUser({ username: '', password: '', role: 'operator' })
      show('✚ User created')
      await load()
    } catch (err) {
      show('✗ ' + (err.message || 'Create failed'), true)
    } finally {
      setBusy(false)
    }
  }

  async function changeRole(u, role) {
    try {
      await api.changeRole(u.id, role)
      show(`Role updated for ${u.username}`)
      await load()
    } catch (err) {
      show('✗ ' + (err.message || 'Role update failed'), true)
    }
  }

  async function toggleActive(u) {
    try {
      await api.setUserActive(u.id, !u.active)
      show(u.active ? `User ${u.username} disabled` : `User ${u.username} enabled`)
      await load()
    } catch (err) {
      show('✗ ' + (err.message || 'Update failed'), true)
    }
  }

  async function resetPassword(u) {
    const pwd = window.prompt(`New password for ${u.username} (min 6 chars):`)
    if (!pwd) return
    try {
      await api.resetUserPassword(u.id, pwd)
      show(`Password reset for ${u.username}`)
    } catch (err) {
      show('✗ ' + (err.message || 'Reset failed'), true)
    }
  }

  return (
    <>
      <PageHeader title="User Management" sub="Admin only · manage accounts, roles and access" />
      {msg && (
        <div className={`chip mb-16 ${msgErr ? 'chip-red' : ''}`}>{msg}</div>
      )}

      <div className="card mb-16">
        <div className="card-header"><h3 className="card-title">Create user</h3></div>
        <form className="flex gap-8" style={{ alignItems: 'flex-end', flexWrap: 'wrap' }} onSubmit={createUser}>
          <div>
            <div className="login-label">Username</div>
            <input className="input" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} required />
          </div>
          <div>
            <div className="login-label">Password</div>
            <input className="input" type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} minLength={6} required />
          </div>
          <div>
            <div className="login-label">Role</div>
            <select className="input" value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
              {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
          </div>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Creating…' : '+ Create'}</button>
        </form>
      </div>

      {loadErr && <div className="card empty">{loadErr}</div>}
      <div className="card">
        <div className="card-header"><h3 className="card-title">Accounts</h3></div>
        <table className="table">
          <thead>
            <tr><th>Username</th><th>Role</th><th>Status</th><th>Created</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td><strong>{u.username}</strong></td>
                <td>
                  <select className="input" style={{ padding: '4px 8px' }} value={u.role} onChange={(e) => changeRole(u, e.target.value)}>
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                  </select>
                </td>
                <td>{u.active ? <span className="badge badge-green">Active</span> : <span className="badge badge-grey">Disabled</span>}</td>
                <td className="muted" style={{ fontSize: 12 }}>{new Date(u.created_at).toLocaleString()}</td>
                <td>
                  <div className="flex gap-4">
                    <button className="btn btn-sm btn-ghost" onClick={() => toggleActive(u)}>
                      {u.active ? 'Disable' : 'Enable'}
                    </button>
                    <button className="btn btn-sm btn-ghost" onClick={() => resetPassword(u)}>Reset pwd</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
