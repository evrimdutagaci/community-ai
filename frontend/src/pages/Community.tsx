import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import { api, type CommunityInfo, type CommunityStub, type CommunityStatus, type Announcement } from '../api/client'

interface ChatEvent {
  type: 'message' | 'system' | 'history' | 'warning' | 'kicked' | 'delete' | 'stream_chunk' | 'stream_end'
  id?: string
  user_id?: string
  sender_id?: string
  username?: string
  sender_username?: string
  is_digital?: boolean
  content?: string
  warning_number?: number
  created_at?: string
  messages?: ChatEvent[]
  isStreaming?: boolean
}

interface Member {
  id: string
  username: string
  is_digital: boolean
}

interface DMUser {
  id: string
  username: string
}

function wsUrl(path: string) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

function digitalName(username: string): string {
  const base = username.split('.')[0]
  return base.charAt(0).toUpperCase() + base.slice(1)
}

function memberDisplayName(m: Member): string {
  return m.is_digital ? digitalName(m.username) : m.username
}

const STATUS_STYLES: Record<CommunityStatus, string> = {
  ACTIVE:    '',
  CANDIDATE: 'bg-blue-100 text-blue-700',
  INACTIVE:  'bg-orange-100 text-orange-700',
  ARCHIVED:  'bg-gray-100 text-gray-500',
}

function StatusBadge({ status }: { status: CommunityStatus }) {
  if (status === 'ACTIVE') return null
  return (
    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full flex-shrink-0 ${STATUS_STYLES[status]}`}>
      {status}
    </span>
  )
}

function Avatar({ name, size = 'md', isDigital = false }: { name: string; size?: 'sm' | 'md'; isDigital?: boolean }) {
  const sz = size === 'sm' ? 'w-6 h-6 text-xs' : 'w-8 h-8 text-sm'
  const bg = isDigital ? 'bg-purple-500' : 'bg-blue-500'
  return (
    <div className={`${sz} ${bg} rounded-full flex items-center justify-center text-white font-semibold flex-shrink-0`}>
      {name[0]?.toUpperCase()}
    </div>
  )
}

function renderContent(content: string, members: Member[], currentUserId?: string): React.ReactNode {
  const parts = content.split(/(@\w+)/g)
  return parts.map((part, i) => {
    if (!part.startsWith('@')) return part
    const name = part.slice(1).toLowerCase()
    const isMention = members.some(
      (m) => memberDisplayName(m).toLowerCase() === name || m.username.toLowerCase() === name
    )
    const isMe = members.some(
      (m) => m.id === currentUserId && memberDisplayName(m).toLowerCase() === name
    )
    if (!isMention) return part
    return (
      <span
        key={i}
        className={`font-semibold rounded px-0.5 ${isMe ? 'bg-yellow-100 text-yellow-800' : 'bg-blue-50 text-blue-700'}`}
      >
        {part}
      </span>
    )
  })
}

const URL_RE = /https?:\/\/[^\s]+/g

function renderDmContent(content: string): React.ReactNode {
  const segments: React.ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null
  URL_RE.lastIndex = 0
  while ((match = URL_RE.exec(content)) !== null) {
    if (match.index > last) segments.push(content.slice(last, match.index))
    const url = match[0].replace(/[.,)]+$/, '')
    const isCalendar = url.includes('calendar.google.com')
    segments.push(
      <a
        key={match.index}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className={`underline font-medium break-all ${isCalendar ? 'text-green-600 hover:text-green-800' : 'text-blue-600 hover:text-blue-800'}`}
      >
        {isCalendar ? '📅 Add to Google Calendar' : url}
      </a>
    )
    last = match.index + match[0].length
  }
  if (last < content.length) segments.push(content.slice(last))
  return segments
}

const SOURCE_COLORS: Record<string, string> = {
  Eventbrite: 'bg-orange-100 text-orange-700',
  Meetup:     'bg-red-100 text-red-700',
  'Lu.ma':    'bg-indigo-100 text-indigo-700',
  Web:        'bg-gray-100 text-gray-600',
}

function SourceBadge({ source }: { source: string }) {
  const cls = SOURCE_COLORS[source] ?? SOURCE_COLORS['Web']
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cls}`}>{source}</span>
  )
}

export default function Community() {
  const [communities, setCommunities] = useState<CommunityStub[]>([])
  const [activeCommunityId, setActiveCommunityId] = useState<string | null>(null)
  const [communityInfo, setCommunityInfo] = useState<CommunityInfo | null>(null)
  const [tab, setTab] = useState<'chat' | 'announcements'>('chat')
  const [events, setEvents] = useState<ChatEvent[]>([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [kicked, setKicked] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const communityBottomRef = useRef<HTMLDivElement>(null)

  const [announcements, setAnnouncements] = useState<Announcement[]>([])
  const [announcementsLoading, setAnnouncementsLoading] = useState(false)

  const [dmUser, setDmUser] = useState<DMUser | null>(null)
  const [dmEvents, setDmEvents] = useState<ChatEvent[]>([])
  const [dmInput, setDmInput] = useState('')
  const [dmConnected, setDmConnected] = useState(false)
  const dmWsRef = useRef<WebSocket | null>(null)
  const dmBottomRef = useRef<HTMLDivElement>(null)

  const { token, user, logout, setUser } = useAuthStore()
  const navigate = useNavigate()

  // Load community list on mount
  useEffect(() => {
    if (!user?.community_id) { navigate('/onboarding'); return }
    api.myCommunities().then((list) => {
      setCommunities(list)
      if (list.length > 0) setActiveCommunityId(list[list.length - 1].id)
    }).catch(() => navigate('/onboarding'))
  }, [])

  // Load active community info when activeCommunityId changes
  useEffect(() => {
    if (!activeCommunityId) return
    api.myCommunity(activeCommunityId).then(setCommunityInfo).catch(() => {})
  }, [activeCommunityId])

  // Community WebSocket — reconnects when activeCommunityId changes
  useEffect(() => {
    if (!activeCommunityId || !token) return
    setEvents([])
    setConnected(false)
    const ws = new WebSocket(`${wsUrl(`/ws/community/${activeCommunityId}`)}?token=${token}`)
    wsRef.current = ws
    ws.onopen = () => setConnected(true)
    ws.onmessage = (e) => {
      const data: ChatEvent = JSON.parse(e.data)
      if (data.type === 'history') { setEvents(data.messages ?? []); return }
      if (data.type === 'delete') {
        setEvents(prev => prev.filter(ev => ev.id !== data.id))
        return
      }
      if (data.type === 'kicked') {
        setKicked(true)
        setTimeout(async () => {
          const u = await api.me()
          setUser(u)
          const remaining = communities.filter(c => c.id !== activeCommunityId)
          if (remaining.length > 0) {
            setCommunities(remaining)
            setActiveCommunityId(remaining[remaining.length - 1].id)
            setKicked(false)
          } else {
            navigate('/onboarding')
          }
        }, 3000)
        return
      }
      if (data.type === 'stream_chunk') {
        const streamId = `streaming_${data.user_id}`
        setEvents(prev => {
          const idx = prev.findIndex(ev => ev.id === streamId)
          if (idx >= 0) {
            const updated = [...prev]
            updated[idx] = { ...updated[idx], content: (updated[idx].content ?? '') + (data.content ?? '') }
            return updated
          }
          return [...prev, { ...data, type: 'message', id: streamId, isStreaming: true, content: data.content ?? '' }]
        })
        return
      }
      if (data.type === 'stream_end') {
        setEvents(prev => prev.map(ev =>
          ev.id === `streaming_${data.user_id}` ? { ...data, type: 'message' } : ev
        ))
        return
      }
      setEvents((prev) => [...prev, data])
    }
    ws.onclose = () => setConnected(false)
    return () => ws.close()
  }, [activeCommunityId, token])

  // DM WebSocket
  useEffect(() => {
    if (!dmUser || !token) return
    setDmEvents([])
    setDmConnected(false)
    const ws = new WebSocket(`${wsUrl(`/ws/dm/${dmUser.id}`)}?token=${token}`)
    dmWsRef.current = ws
    ws.onopen = () => setDmConnected(true)
    ws.onmessage = (e) => {
      const data: ChatEvent = JSON.parse(e.data)
      if (data.type === 'history') { setDmEvents(data.messages ?? []); return }
      if (data.type === 'stream_chunk') {
        const streamId = `streaming_${data.sender_id}`
        setDmEvents(prev => {
          const idx = prev.findIndex(ev => ev.id === streamId)
          if (idx >= 0) {
            const updated = [...prev]
            updated[idx] = { ...updated[idx], content: (updated[idx].content ?? '') + (data.content ?? '') }
            return updated
          }
          return [...prev, { ...data, type: 'message', id: streamId, isStreaming: true, content: data.content ?? '' }]
        })
        return
      }
      if (data.type === 'stream_end') {
        setDmEvents(prev => prev.map(ev =>
          ev.id === `streaming_${data.sender_id}` ? { ...data, type: 'message' } : ev
        ))
        return
      }
      setDmEvents((prev) => [...prev, data])
    }
    ws.onclose = () => setDmConnected(false)
    return () => ws.close()
  }, [dmUser?.id, token])

  // Fetch announcements when tab switches or community changes
  useEffect(() => {
    if (tab !== 'announcements' || !activeCommunityId) return
    setAnnouncementsLoading(true)
    api.getAnnouncements(activeCommunityId)
      .then(setAnnouncements)
      .catch(() => setAnnouncements([]))
      .finally(() => setAnnouncementsLoading(false))
  }, [tab, activeCommunityId])

  // Reset tab to chat when switching communities
  useEffect(() => { setTab('chat') }, [activeCommunityId])

  useEffect(() => { communityBottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [events])
  useEffect(() => { dmBottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [dmEvents])

  async function leaveActive() {
    if (!activeCommunityId) return
    await api.leaveCommunity(activeCommunityId)
    const remaining = communities.filter(c => c.id !== activeCommunityId)
    const updatedUser = await api.me()
    setUser(updatedUser)
    if (remaining.length > 0) {
      setCommunities(remaining)
      setActiveCommunityId(remaining[remaining.length - 1].id)
    } else {
      navigate('/onboarding')
    }
  }

  async function findNewCommunity() {
    await api.startCommunitySearch()
    const updatedUser = await api.me()
    setUser(updatedUser)
    navigate('/onboarding')
  }

  function sendCommunity() {
    const content = input.trim()
    if (!content || wsRef.current?.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({ content }))
    setInput('')
  }

  function sendDM() {
    const content = dmInput.trim()
    if (!content || dmWsRef.current?.readyState !== WebSocket.OPEN) return
    dmWsRef.current.send(JSON.stringify({ content }))
    setDmInput('')
  }

  function openDM(member: Member) {
    setDmUser({ id: member.id, username: memberDisplayName(member) })
  }

  function closeDM() {
    setDmUser(null)
    setDmEvents([])
  }

  const members = communityInfo?.members ?? []

  return (
    <div className="min-h-screen flex">
      {kicked && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-8 max-w-sm w-full text-center shadow-2xl mx-4">
            <div className="text-4xl mb-3">🚫</div>
            <h2 className="text-lg font-bold text-gray-900 mb-2">Removed from community</h2>
            <p className="text-sm text-gray-500">You received 3 moderator warnings and have been removed.</p>
          </div>
        </div>
      )}

      {/* Sidebar */}
      <aside className="w-60 bg-white border-r flex flex-col flex-shrink-0">
        {/* Communities list */}
        <div className="p-4 border-b">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Communities</p>
          {communities.map((c) => (
            <button
              key={c.id}
              onClick={() => { setActiveCommunityId(c.id); setDmUser(null) }}
              className={`w-full text-left px-2 py-1.5 rounded-lg text-sm transition-colors mb-0.5 flex items-center gap-1.5 ${
                c.id === activeCommunityId
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${c.id === activeCommunityId ? 'bg-blue-500' : 'bg-gray-300'}`} />
              <span className="truncate flex-1">{c.name}</span>
              <StatusBadge status={c.status} />
            </button>
          ))}
        </div>

        {/* Active community members */}
        {communityInfo && (
          <div className="p-4 flex-1 overflow-y-auto">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Members</p>
            {communityInfo.description && (
              <p className="text-xs text-gray-400 mb-3 leading-relaxed">{communityInfo.description}</p>
            )}
            {members.map((m) => {
              const isMe = m.id === user?.id
              const clickable = !m.is_digital && !isMe
              return (
                <div
                  key={m.id}
                  className={`flex items-center gap-2 py-1.5 px-1 rounded-lg ${
                    clickable ? 'cursor-pointer hover:bg-gray-100 transition-colors' : ''
                  } ${dmUser?.id === m.id ? 'bg-blue-50' : ''}`}
                  onClick={() => clickable && openDM(m)}
                >
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${m.is_digital ? 'bg-purple-400' : 'bg-green-400'}`} />
                  <span className="text-sm text-gray-700 truncate flex-1">{memberDisplayName(m)}</span>
                  {m.is_digital
                    ? <span className="text-xs text-purple-400 font-medium">AI</span>
                    : isMe
                    ? <span className="text-xs text-gray-400">you</span>
                    : null
                  }
                </div>
              )
            })}
          </div>
        )}

        <div className="p-4 border-t space-y-2">
          <button onClick={findNewCommunity} className="w-full text-sm text-blue-600 hover:text-blue-800 transition-colors text-left">
            Find new community
          </button>
          {activeCommunityId && (
            <button onClick={leaveActive} className="w-full text-sm text-red-400 hover:text-red-600 transition-colors text-left">
              Leave this community
            </button>
          )}
          {user?.is_admin && (
            <button onClick={() => navigate('/admin')} className="w-full text-sm text-purple-600 hover:text-purple-800 transition-colors text-left">
              Admin panel
            </button>
          )}
          <button onClick={() => navigate('/settings')} className="w-full text-sm text-gray-600 hover:text-gray-900 transition-colors text-left">
            Settings
          </button>
          <button onClick={() => { logout(); navigate('/login') }} className="text-sm text-gray-500 hover:text-gray-800 transition-colors">
            Sign out
          </button>
        </div>
      </aside>

      {/* Main area */}
      {dmUser ? (
        <div className="flex-1 flex flex-col min-w-0">
          <div className="bg-white border-b px-5 py-3 flex items-center gap-3">
            <button onClick={closeDM} className="text-gray-400 hover:text-gray-700 text-sm transition-colors">
              ← Back
            </button>
            <Avatar name={dmUser.username} size="sm" />
            <span className="font-medium text-gray-900">{dmUser.username}</span>
            <span className={`ml-auto text-xs font-medium ${dmConnected ? 'text-green-500' : 'text-red-400'}`}>
              {dmConnected ? 'live' : 'connecting…'}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
            {dmEvents.map((ev, i) => {
              const isMe = ev.sender_id === user?.id
              return (
                <div key={ev.id ?? i} className={`flex gap-3 ${isMe ? 'flex-row-reverse' : ''}`}>
                  <Avatar name={isMe ? (user?.username ?? '?') : dmUser.username} />
                  <div className={`flex flex-col gap-0.5 max-w-[70%] ${isMe ? 'items-end' : 'items-start'}`}>
                    <div className={`rounded-2xl px-4 py-2 text-sm leading-relaxed ${isMe ? 'bg-blue-600 text-white' : 'bg-white border shadow-sm text-gray-800'}`}>
                      {ev.content ? renderDmContent(ev.content) : null}
                      {ev.isStreaming && <span className="inline-block w-0.5 h-3.5 bg-current opacity-70 animate-pulse ml-0.5 align-middle" />}
                    </div>
                  </div>
                </div>
              )
            })}
            {dmEvents.length === 0 && dmConnected && (
              <p className="text-center text-sm text-gray-400 pt-8">No messages yet. Say hello!</p>
            )}
            <div ref={dmBottomRef} />
          </div>

          <div className="bg-white border-t px-5 py-4">
            <div className="flex gap-3">
              <input
                type="text"
                value={dmInput}
                onChange={(e) => setDmInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendDM()}
                placeholder={dmConnected ? `Message ${dmUser.username}…` : 'Connecting…'}
                disabled={!dmConnected}
                className="flex-1 border rounded-full px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-40"
              />
              <button
                onClick={sendDM}
                disabled={!dmConnected || !dmInput.trim()}
                className="bg-blue-600 text-white rounded-full px-5 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-40 transition-colors"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header with tabs */}
          <div className="bg-white border-b px-5 py-0 flex items-center gap-6">
            <span className="font-medium text-gray-900 py-3">
              {communityInfo ? `# ${communityInfo.name}` : '# community-chat'}
            </span>
            <div className="flex gap-0 ml-2">
              <button
                onClick={() => setTab('chat')}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${tab === 'chat' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
              >
                Chat
              </button>
              <button
                onClick={() => setTab('announcements')}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${tab === 'announcements' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
              >
                Events
              </button>
            </div>
            <span className={`ml-auto text-xs font-medium ${connected ? 'text-green-500' : 'text-red-400'}`}>
              {tab === 'chat' ? (connected ? 'live' : 'offline') : ''}
            </span>
          </div>

          {tab === 'chat' ? (
            <>
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
                {events.map((ev, i) => {
                  if (ev.type === 'system') {
                    return <div key={i} className="text-center text-xs text-gray-400 py-1">{ev.content}</div>
                  }
                  if (ev.type === 'warning') {
                    return (
                      <div key={i} className="text-center py-1">
                        <span className="inline-block bg-yellow-50 text-yellow-800 border border-yellow-200 rounded-full px-4 py-1 text-xs font-medium">
                          {ev.content}
                        </span>
                      </div>
                    )
                  }
                  const isMe = ev.user_id === user?.id
                  const isDigital = ev.is_digital ?? false
                  const displayUsername = isDigital && ev.username ? digitalName(ev.username) : (ev.username ?? '?')
                  return (
                    <div key={ev.id ?? i} className={`flex gap-3 ${isMe ? 'flex-row-reverse' : ''}`}>
                      <Avatar name={displayUsername} isDigital={isDigital} />
                      <div className={`flex flex-col gap-0.5 max-w-[70%] ${isMe ? 'items-end' : 'items-start'}`}>
                        {!isMe && (
                          <span className="flex items-center gap-1 text-xs font-medium text-gray-500 px-1">
                            {displayUsername}
                            {isDigital && (
                              <span className="bg-purple-100 text-purple-600 rounded-full px-1.5 py-0.5 text-[10px] font-semibold">AI</span>
                            )}
                          </span>
                        )}
                        <div className={`rounded-2xl px-4 py-2 text-sm leading-relaxed ${isMe ? 'bg-blue-600 text-white' : isDigital ? 'bg-purple-50 border border-purple-100 text-gray-800' : 'bg-white border shadow-sm text-gray-800'}`}>
                          {ev.content ? renderContent(ev.content, members, user?.id) : null}
                          {ev.isStreaming && <span className="inline-block w-0.5 h-3.5 bg-current opacity-70 animate-pulse ml-0.5 align-middle" />}
                        </div>
                      </div>
                    </div>
                  )
                })}
                <div ref={communityBottomRef} />
              </div>

              <div className="bg-white border-t px-5 py-4">
                <div className="flex gap-3">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && sendCommunity()}
                    placeholder={connected ? 'Message the community…' : 'Reconnecting…'}
                    disabled={!connected}
                    className="flex-1 border rounded-full px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-40"
                  />
                  <button
                    onClick={sendCommunity}
                    disabled={!connected || !input.trim()}
                    className="bg-blue-600 text-white rounded-full px-5 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-40 transition-colors"
                  >
                    Send
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 overflow-y-auto px-5 py-6">
              <div className="max-w-2xl mx-auto">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="font-semibold text-gray-900">Today's Events</h2>
                    <p className="text-xs text-gray-400 mt-0.5">
                      Events related to this community{communityInfo?.description ? ` · ${communityInfo.description}` : ''}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      if (!activeCommunityId) return
                      setAnnouncementsLoading(true)
                      api.getAnnouncements(activeCommunityId)
                        .then(setAnnouncements)
                        .catch(() => {})
                        .finally(() => setAnnouncementsLoading(false))
                    }}
                    className="text-xs text-blue-600 hover:text-blue-800 transition-colors"
                  >
                    Refresh
                  </button>
                </div>

                {announcementsLoading ? (
                  <div className="text-center py-16 text-gray-400 text-sm">Searching for events…</div>
                ) : announcements.length === 0 ? (
                  <div className="text-center py-16 text-gray-400 text-sm">No events found for today.</div>
                ) : (
                  <div className="space-y-3">
                    {announcements.map((ann) => (
                      <div key={ann.id} className="bg-white border rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow">
                        <div className="flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1.5">
                              <SourceBadge source={ann.source} />
                            </div>
                            <h3 className="font-medium text-gray-900 text-sm leading-snug">{ann.title}</h3>
                            {ann.description && (
                              <p className="text-xs text-gray-500 mt-1 line-clamp-2 leading-relaxed">{ann.description}</p>
                            )}
                          </div>
                          {ann.event_url && (
                            <a
                              href={ann.event_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex-shrink-0 text-xs font-medium text-blue-600 hover:text-blue-800 hover:underline transition-colors"
                            >
                              View →
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
