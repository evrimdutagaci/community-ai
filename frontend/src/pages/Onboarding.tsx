import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import { api, type CommunityStub, type CommunityStatus } from '../api/client'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface Recommendation {
  id: string
  name: string
  description: string
  similarity: number
  status: CommunityStatus
}

const STATUS_LABEL: Partial<Record<CommunityStatus, { label: string; cls: string }>> = {
  CANDIDATE: { label: 'New',      cls: 'bg-blue-100 text-blue-700' },
  INACTIVE:  { label: 'Inactive', cls: 'bg-orange-100 text-orange-700' },
  ARCHIVED:  { label: 'Archived', cls: 'bg-gray-100 text-gray-500' },
}

// Match ws/wss to the page protocol so the connection works on both HTTP (dev) and HTTPS (prod)
function wsUrl(path: string) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

export default function Onboarding() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const [recommendations, setRecommendations] = useState<Recommendation[] | null>(null)
  const [currentCommunities, setCurrentCommunities] = useState<CommunityStub[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const { token, user, setUser } = useAuthStore()
  const navigate = useNavigate()

  // hasCommunity is true when the user is searching for an additional community while already
  // being a member of at least one — the sidebar only renders in this secondary-search mode
  const hasCommunity = !!user?.community_id

  useEffect(() => {
    if (hasCommunity) {
      api.myCommunities().then(setCurrentCommunities).catch(() => {})
    }
  }, [hasCommunity])

  useEffect(() => {
    const ws = new WebSocket(`${wsUrl('/ws/onboarding')}?token=${token}`)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)

      if (data.type === 'history') {
        setMessages(data.messages as ChatMessage[])
        return
      }

      if (data.type === 'recommendations') {
        setRecommendations(data.communities as Recommendation[])
        return
      }

      if (data.type === 'onboarding_complete') {
        setFinishing(true)
        setRecommendations(null)
        // Brief delay so the "Joining…" indicator is visible before navigating
        setTimeout(async () => {
          const u = await api.me()
          setUser(u)
          navigate('/community')
        }, 1500)
        return
      }

      if (data.type === 'message') {
        setMessages((prev) => [...prev, { role: data.role, content: data.content }])
      }
    }

    ws.onclose = (e) => {
      setConnected(false)
      // Close code 4002 means the server detected the user is already onboarded —
      // redirect without re-running the onboarding flow
      if (e.code === 4002) {
        api.me().then((u) => { setUser(u); navigate('/community') })
      }
    }
    return () => ws.close()
  }, [token])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, recommendations])

  function send() {
    const content = input.trim()
    if (!content || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    setMessages((prev) => [...prev, { role: 'user', content }])
    wsRef.current.send(JSON.stringify({ content }))
    setInput('')
  }

  // communityId === null signals the backend to create a brand-new community for the user
  function joinCommunity(communityId: string | null) {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({ type: 'join', community_id: communityId }))
    setRecommendations(null)
    setFinishing(true)
  }

  const inputDisabled = !connected || finishing

  return (
    <div className="min-h-screen flex">
      {/* Sidebar — only shown when user already belongs to a community */}
      {hasCommunity && (
        <aside className="w-56 bg-white border-r flex flex-col flex-shrink-0">
          <div className="p-4 border-b flex-1 overflow-y-auto">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Your communities</p>
            {currentCommunities.length === 0 && <p className="text-sm text-gray-400">…</p>}
            {currentCommunities.map((c) => (
              <button
                key={c.id}
                onClick={() => navigate('/community')}
                className="w-full text-left px-2 py-1.5 rounded-lg text-sm text-gray-700 hover:bg-gray-100 transition-colors truncate mb-0.5 block"
              >
                {c.name}
              </button>
            ))}
          </div>
          <div className="p-4 border-t">
            <button
              onClick={() => navigate('/community')}
              className="w-full text-sm text-blue-600 hover:text-blue-800 transition-colors text-left"
            >
              ← Back to community
            </button>
          </div>
        </aside>
      )}

      {/* Main onboarding area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="bg-white border-b px-6 py-4">
          <h1 className="text-lg font-semibold">
            {hasCommunity ? 'Find a new community' : 'Finding your community'}
          </h1>
          <p className="text-sm text-gray-500">
            {hasCommunity
              ? 'Chat with our AI — it\'ll find you a better match'
              : 'Chat with our AI — it\'ll match you with like-minded people'}
          </p>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 max-w-2xl mx-auto w-full">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`rounded-2xl px-4 py-3 max-w-[80%] text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white border shadow-sm text-gray-800'
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}

          {/* Community recommendations */}
          {recommendations !== null && !finishing && (
            <div className="space-y-3 pt-2">
              <p className="text-sm font-semibold text-gray-700 text-center">
                {recommendations.length > 0
                  ? 'Here are communities that match your profile:'
                  : "You'll be the first in a brand new community!"}
              </p>

              {recommendations.map((rec) => (
                <div key={rec.id} className="bg-white border rounded-xl p-4 shadow-sm flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-gray-900 truncate">{rec.name}</h3>
                      <span className="text-xs text-blue-500 font-medium flex-shrink-0">
                        {Math.round(rec.similarity * 100)}% match
                      </span>
                      {STATUS_LABEL[rec.status] && (
                        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full flex-shrink-0 ${STATUS_LABEL[rec.status]!.cls}`}>
                          {STATUS_LABEL[rec.status]!.label}
                        </span>
                      )}
                    </div>
                    {rec.description && (
                      <p className="text-sm text-gray-500 mt-0.5">{rec.description}</p>
                    )}
                  </div>
                  <button
                    onClick={() => joinCommunity(rec.id)}
                    className="bg-blue-600 text-white rounded-full px-4 py-1.5 text-sm font-medium hover:bg-blue-700 transition-colors flex-shrink-0"
                  >
                    Join
                  </button>
                </div>
              ))}

              <button
                onClick={() => joinCommunity(null)}
                className="w-full border border-dashed border-gray-300 rounded-xl p-3 text-sm text-gray-500 hover:border-blue-400 hover:text-blue-600 transition-colors"
              >
                + Create a new community for me instead
              </button>

              <p className="text-xs text-center text-gray-400 pt-1">
                Not quite right? Keep chatting below and recommendations will update.
              </p>
            </div>
          )}

          {finishing && (
            <div className="text-center py-4">
              <div className="inline-flex items-center gap-2 bg-green-50 text-green-700 border border-green-200 rounded-full px-5 py-2 text-sm font-medium">
                <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                Joining your community…
              </div>
            </div>
          )}

          {!connected && !finishing && (
            <div className="text-center text-xs text-gray-400">Connecting…</div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="bg-white border-t px-4 py-4">
          <div className="max-w-2xl mx-auto flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
              placeholder={recommendations ? 'Keep chatting to refine recommendations…' : 'Tell us about yourself…'}
              disabled={inputDisabled}
              className="flex-1 border rounded-full px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-40"
            />
            <button
              onClick={send}
              disabled={inputDisabled || !input.trim()}
              className="bg-blue-600 text-white rounded-full px-5 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-40 transition-colors"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
