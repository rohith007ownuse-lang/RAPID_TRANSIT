import { useState, useRef, useEffect } from 'react'
import { api } from '../api.js'

const QUICK_QUERIES = [
  'What is the fleet status?',
  'Which buses are at highest risk?',
  'Show critical incidents',
  'Which buses need intervention?',
  'Show demand overview',
  'Rebalancing recommendations',
  'Which emergency facilities are available?',
]

function CopilotMessage({ msg, index }) {
  const isUser = msg.role === 'user'
  return (
    <div style={{
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      marginBottom: 8,
    }}>
      <div style={{
        maxWidth: '80%',
        padding: '8px 12px',
        borderRadius: 12,
        background: isUser ? '#2563eb' : '#1e293b',
        color: '#e2e8f0',
        fontSize: 12,
        lineHeight: 1.5,
        borderTopRightRadius: isUser ? 4 : 12,
        borderTopLeftRadius: isUser ? 12 : 4,
      }}>
        {!isUser && (
          <div style={{ fontSize: 10, color: '#94a3b8', marginBottom: 4, fontWeight: 600 }}>
            AI COPILOT
          </div>
        )}
        <div>{msg.text}</div>
        {msg.data && (
          <div style={{ marginTop: 6, fontSize: 10, color: '#94a3b8' }}>
            Source: {msg.data_source || 'System'} | Confidence: {msg.confidence != null ? `${(msg.confidence * 100).toFixed(0)}%` : 'N/A'}
          </div>
        )}
      </div>
    </div>
  )
}

export default function AICopilot({ compact = false }) {
  const [messages, setMessages] = useState([
    {
      role: 'copilot',
      text: 'Hello! I am the AI Control Centre Copilot. I can help you with fleet status, bus details, incidents, risks, demand, and emergency facilities. What would you like to know?',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleQuery = async (question) => {
    if (!question.trim()) return

    const userMsg = { role: 'user', text: question }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const result = await api.v2CopilotQuery(question)
      const copilotMsg = {
        role: 'copilot',
        text: result.answer || 'I could not find an answer to that question.',
        data: result.data,
        data_source: result.data_source,
        confidence: result.confidence,
      }
      setMessages((prev) => [...prev, copilotMsg])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'copilot', text: `Error: ${err.message || 'Failed to process query'}` },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    handleQuery(input)
  }

  if (compact) {
    return (
      <div className="card mb-16" style={{ borderLeft: '4px solid #8b5cf6' }}>
        <div className="card-header">
          <h3 className="card-title">🤖 AI Copilot</h3>
          <span className="badge badge-blue" style={{ fontSize: 10 }}>INTERACTIVE</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about fleet, risks, incidents..."
            className="input"
            style={{ flex: 1, fontSize: 12, padding: '6px 10px' }}
            onKeyDown={(e) => e.key === 'Enter' && handleQuery(input)}
            disabled={loading}
          />
          <button
            className="btn btn-primary"
            style={{ fontSize: 12, padding: '6px 14px' }}
            onClick={() => handleQuery(input)}
            disabled={loading || !input.trim()}
          >
            {loading ? '...' : 'Ask'}
          </button>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
          {QUICK_QUERIES.slice(0, 4).map((q) => (
            <button
              key={q}
              className="btn btn-ghost"
              style={{ fontSize: 10, padding: '3px 8px' }}
              onClick={() => handleQuery(q)}
              disabled={loading}
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="card mb-16" style={{ borderLeft: '4px solid #8b5cf6' }}>
      <div className="card-header">
        <h3 className="card-title">🤖 AI Control Centre Copilot</h3>
        <span className="badge badge-blue" style={{ fontSize: 10 }}>
          {messages.length - 1} EXCHANGES
        </span>
      </div>

      {/* Messages */}
      <div style={{
        maxHeight: 350,
        overflowY: 'auto',
        padding: '8px 0',
        borderBottom: '1px solid #e2e8f0',
      }}>
        {messages.map((msg, i) => (
          <CopilotMessage key={i} msg={msg} index={i} />
        ))}
        {loading && (
          <div style={{ textAlign: 'center', color: '#94a3b8', fontSize: 12, padding: 8 }}>
            Thinking...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick queries */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, padding: '8px 0' }}>
        {QUICK_QUERIES.map((q) => (
          <button
            key={q}
            className="btn btn-ghost"
            style={{ fontSize: 10, padding: '3px 8px' }}
            onClick={() => handleQuery(q)}
            disabled={loading}
          >
            {q}
          </button>
        ))}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about fleet, risks, incidents, demand, emergency..."
          className="input"
          style={{ flex: 1, fontSize: 12, padding: '8px 12px' }}
          disabled={loading}
        />
        <button
          type="submit"
          className="btn btn-primary"
          style={{ fontSize: 12, padding: '8px 16px' }}
          disabled={loading || !input.trim()}
        >
          {loading ? '...' : 'Send'}
        </button>
      </form>
    </div>
  )
}
