import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * SuggestSearch — suggestion-style search used everywhere in the control
 * centre. Typing the first letters/characters instantly suggests matching
 * items (bus ids, registration numbers, route codes); each extra character
 * narrows the suggestion list. No need to know the full name to find a bus.
 *
 * props:
 *  - items:        [{ key, label, sublabel?, keywords? }] — searchable catalogue
 *  - placeholder:  input placeholder text
 *  - onSelect:     (item) => void — fired when a suggestion is picked
 *  - onQuery:      (query) => void — live query callback (for filtering lists)
 *  - maxResults:   cap on shown suggestions (default 8)
 */
export default function SuggestSearch({ items = [], placeholder = 'Search…', onSelect, onQuery, maxResults = 8, style }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const boxRef = useRef(null)

  useEffect(() => { onQuery?.(query) }, [query]) // eslint-disable-line react-hooks/exhaustive-deps

  // close on outside click
  useEffect(() => {
    const close = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const q = query.trim().toLowerCase()
  const matches = useMemo(() => {
    if (!q) return []
    const scored = []
    for (const it of items) {
      const label = (it.label || '').toLowerCase()
      const sub = (it.sublabel || '').toLowerCase()
      const kw = (it.keywords || '').toLowerCase()
      // prefix match on the main label ranks first, then substring matches
      let score = -1
      if (label.startsWith(q)) score = 0
      else if (label.includes(q)) score = 1
      else if (sub.includes(q)) score = 2
      else if (kw.includes(q)) score = 3
      if (score >= 0) scored.push({ it, score })
    }
    scored.sort((a, b) => a.score - b.score || a.it.label.localeCompare(b.it.label))
    return scored.slice(0, maxResults).map((s) => s.it)
  }, [q, items, maxResults])

  const pick = (it) => {
    setQuery('')
    setOpen(false)
    onSelect?.(it)
  }

  return (
    <div ref={boxRef} style={{ position: 'relative', ...style }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, border: '1px solid var(--border)', borderRadius: 8, padding: '4px 8px', background: '#fff' }}>
        <span style={{ fontSize: 13, color: '#6b7280' }}>🔍</span>
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setHi(0) }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (!open || matches.length === 0) return
            if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, matches.length - 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)) }
            else if (e.key === 'Enter') { e.preventDefault(); if (matches[hi]) pick(matches[hi]) }
            else if (e.key === 'Escape') setOpen(false)
          }}
          placeholder={placeholder}
          style={{ border: 'none', outline: 'none', fontSize: 12, padding: '3px 2px', flex: 1, minWidth: 120, background: 'transparent' }}
        />
        {query && (
          <button
            onClick={() => { setQuery(''); setOpen(false) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', fontSize: 12, padding: 0 }}
            title="Clear"
          >
            ✕
          </button>
        )}
      </div>
      {open && q && (
        <div
          style={{
            position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 1200,
            background: '#fff', border: '1px solid var(--border)', borderRadius: 8,
            boxShadow: '0 8px 24px rgba(0,0,0,.14)', marginTop: 4, overflow: 'hidden',
          }}
        >
          {matches.length === 0 ? (
            <div className="muted" style={{ fontSize: 12, padding: '8px 10px' }}>No matches for "{query}"</div>
          ) : (
            matches.map((it, i) => (
              <button
                key={it.key}
                onMouseEnter={() => setHi(i)}
                onClick={() => pick(it)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', border: 'none',
                  background: i === hi ? '#eef4fb' : '#fff', cursor: 'pointer',
                  padding: '7px 10px', fontSize: 12.5,
                  borderBottom: '1px solid #f1f5f9',
                }}
              >
                {it.kind && (
                  <span
                    className="badge"
                    style={{ fontSize: 9, marginRight: 6, background: '#eef2ff', color: '#3730a3' }}
                  >
                    {it.kind.replace(/_/g, ' ').toUpperCase()}
                  </span>
                )}
                <strong>{it.label}</strong>
                {it.sublabel && <span className="muted" style={{ marginLeft: 8, fontSize: 11 }}>{it.sublabel}</span>}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
