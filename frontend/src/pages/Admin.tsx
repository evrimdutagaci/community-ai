import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import {
  api,
  type AdminStats, type AdminCommunity, type AdminCommunityDetail,
  type AdminUser, type AdminUserDetail, type AdminWarning, type AdminLog,
  type CommunityStatus, type MetricsSnapshot,
} from '../api/client'

type Tab = 'dashboard' | 'communities' | 'users' | 'moderation' | 'logs' | 'metrics'

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border p-5">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

const STATUS_BADGE: Record<CommunityStatus, { label: string; color: 'red' | 'yellow' | 'green' | 'blue' | 'purple' | 'gray' }> = {
  ACTIVE:    { label: 'Active',    color: 'green' },
  CANDIDATE: { label: 'Candidate', color: 'blue' },
  INACTIVE:  { label: 'Inactive',  color: 'yellow' },
  ARCHIVED:  { label: 'Archived',  color: 'gray' },
}

function Badge({ children, color = 'gray' }: { children: React.ReactNode; color?: 'red' | 'yellow' | 'green' | 'blue' | 'purple' | 'gray' }) {
  const colors = {
    red: 'bg-red-100 text-red-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    green: 'bg-green-100 text-green-700',
    blue: 'bg-blue-100 text-blue-700',
    purple: 'bg-purple-100 text-purple-700',
    gray: 'bg-gray-100 text-gray-600',
  }
  return <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors[color]}`}>{children}</span>
}

function Confirm({ message, onConfirm, onCancel }: { message: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 max-w-sm w-full mx-4 shadow-xl">
        <p className="text-sm text-gray-700 mb-5">{message}</p>
        <div className="flex gap-3 justify-end">
          <button onClick={onCancel} className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2">Cancel</button>
          <button onClick={onConfirm} className="bg-red-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-red-700">Confirm</button>
        </div>
      </div>
    </div>
  )
}

interface Field {
  key: string
  label: string
  type?: 'text' | 'email' | 'password' | 'textarea' | 'checkbox'
  required?: boolean
  placeholder?: string
}

function EditModal({
  title,
  fields,
  initial,
  onSave,
  onClose,
}: {
  title: string
  fields: Field[]
  initial: Record<string, string | boolean>
  onSave: (values: Record<string, string | boolean>) => Promise<void>
  onClose: () => void
}) {
  const [values, setValues] = useState<Record<string, string | boolean>>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave(values)
      onClose()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const inputCls = 'w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400'

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 max-w-md w-full mx-4 shadow-xl">
        <h3 className="font-semibold text-gray-900 mb-4">{title}</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          {fields.map((f) => (
            <div key={f.key}>
              <label className="block text-sm font-medium text-gray-700 mb-1">{f.label}</label>
              {f.type === 'textarea' ? (
                <textarea
                  className={`${inputCls} resize-none h-20`}
                  value={values[f.key] as string ?? ''}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                />
              ) : f.type === 'checkbox' ? (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={values[f.key] as boolean ?? false}
                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.checked }))}
                    className="w-4 h-4 rounded border-gray-300 text-blue-600"
                  />
                  <span className="text-sm text-gray-600">Enabled</span>
                </label>
              ) : (
                <input
                  type={f.type ?? 'text'}
                  className={inputCls}
                  value={values[f.key] as string ?? ''}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  required={f.required}
                  placeholder={f.placeholder}
                  autoComplete="off"
                />
              )}
            </div>
          ))}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3 justify-end pt-1">
            <button type="button" onClick={onClose} className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="bg-blue-600 text-white text-sm px-5 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function CommunityEditModal({
  community,
  onSave,
  onClose,
}: {
  community: AdminCommunityDetail & { location?: string | null }
  onSave: (vals: { name: string; description: string; location: string; status: string }) => Promise<void>
  onClose: () => void
}) {
  const [name, setName] = useState(community.name)
  const [description, setDescription] = useState(community.description ?? '')
  const [location, setLocation] = useState((community as any).location ?? '')
  const [status, setStatus] = useState<CommunityStatus>(community.status)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) { setError('Name cannot be empty'); return }
    setSaving(true)
    setError(null)
    try {
      await onSave({ name: name.trim(), description: description.trim(), location: location.trim(), status })
      onClose()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const inputCls = 'w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400'
  const statuses: CommunityStatus[] = ['ACTIVE', 'CANDIDATE', 'INACTIVE', 'ARCHIVED']

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 max-w-md w-full mx-4 shadow-xl">
        <h3 className="font-semibold text-gray-900 mb-4">Edit community</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              className={`${inputCls} resize-none h-20`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional…"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Location</label>
            <input
              className={inputCls}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Berlin, San Francisco, online"
            />
            <p className="text-xs text-gray-400 mt-1">
              Used to filter local events in the Events tab. Leave blank for global/online search.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
            <div className="flex gap-2 flex-wrap">
              {statuses.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(s)}
                  className={`text-xs font-medium px-3 py-1.5 rounded-full border-2 transition-all ${
                    status === s
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-gray-200 text-gray-600 hover:border-gray-300'
                  }`}
                >
                  {STATUS_BADGE[s].label}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              Overrides the automatic status computed from activity and member count.
            </p>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3 justify-end pt-1">
            <button type="button" onClick={onClose} className="text-sm text-gray-500 hover:text-gray-800 px-4 py-2">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="bg-blue-600 text-white text-sm px-5 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Dashboard ────────────────────────────────────────────────────────────────

function Dashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null)

  useEffect(() => { api.adminStats().then(setStats).catch(() => {}) }, [])

  if (!stats) return <div className="text-sm text-gray-400 p-6">Loading…</div>

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Overview</h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Real users" value={stats.users.total} />
        <StatCard label="Communities" value={stats.communities.total} />
        <StatCard label="Total messages" value={stats.messages.total} sub={`${stats.messages.today} today`} />
        <StatCard label="Active warnings" value={stats.warnings.active} />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Digital members" value={stats.users.digital} />
        <StatCard label="Direct messages" value={stats.messages.dms} />
      </div>
    </div>
  )
}

// ── Communities ──────────────────────────────────────────────────────────────

function Communities() {
  const [communities, setCommunities] = useState<AdminCommunity[]>([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<AdminCommunityDetail | null>(null)
  const [confirm, setConfirm] = useState<{ action: () => void; message: string } | null>(null)
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    api.adminCommunities(search).then(setCommunities).finally(() => setLoading(false))
  }, [search])

  useEffect(() => { load() }, [load])

  async function openDetail(id: string) {
    const detail = await api.adminCommunity(id)
    setSelected(detail)
  }

  async function handleArchive(id: string, name: string) {
    setConfirm({
      message: `Archive community "${name}"? Members will still see it but it will be marked as archived.`,
      action: async () => {
        await api.deleteCommunity(id)
        setConfirm(null)
        const detail = await api.adminCommunity(id)
        setSelected(detail)
        load()
      },
    })
  }

  async function handleKick(userId: string, communityId: string, username: string) {
    setConfirm({
      message: `Remove ${username} from this community?`,
      action: async () => {
        await api.kickUserFromCommunity(userId, communityId)
        setConfirm(null)
        openDetail(communityId)
      },
    })
  }

  if (selected) {
    return (
      <div className="p-6">
        {confirm && <Confirm message={confirm.message} onConfirm={confirm.action} onCancel={() => setConfirm(null)} />}
        {editing && (
          <CommunityEditModal
            community={selected}
            onSave={async (vals) => {
              await api.updateAdminCommunity(selected.id, vals)
              const detail = await api.adminCommunity(selected.id)
              setSelected(detail)
              load()
            }}
            onClose={() => setEditing(false)}
          />
        )}
        <div className="flex items-center gap-3 mb-5">
          <button onClick={() => setSelected(null)} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
          <h2 className="text-lg font-semibold text-gray-900">{selected.name}</h2>
          <button onClick={() => setEditing(true)} className="text-sm text-blue-500 hover:text-blue-700">
            Edit
          </button>
          <div className="ml-auto flex items-center gap-3">
            <Badge color={STATUS_BADGE[selected.status].color}>{STATUS_BADGE[selected.status].label}</Badge>
            {selected.status !== 'ARCHIVED' && (
              <button
                onClick={() => handleArchive(selected.id, selected.name)}
                className="text-sm text-red-500 hover:text-red-700"
              >
                Archive
              </button>
            )}
          </div>
        </div>

        {selected.description && <p className="text-sm text-gray-500 mb-5">{selected.description}</p>}

        <div className="grid grid-cols-3 gap-4 mb-6">
          <StatCard label="Real members" value={selected.real_member_count} />
          <StatCard label="AI members" value={selected.digital_member_count} />
          <StatCard label="Messages" value={selected.message_count} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Members</h3>
            <div className="space-y-1">
              {selected.members.map((m) => (
                <div key={m.id} className="flex items-center gap-2 py-2 px-3 bg-white border rounded-lg">
                  <span className={`w-2 h-2 rounded-full ${m.is_digital ? 'bg-purple-400' : 'bg-green-400'}`} />
                  <span className="text-sm text-gray-800 flex-1">{m.username}</span>
                  {m.is_digital
                    ? <Badge color="purple">AI</Badge>
                    : (
                      <button
                        onClick={() => handleKick(m.id, selected.id, m.username)}
                        className="text-xs text-red-400 hover:text-red-600"
                      >
                        Kick
                      </button>
                    )
                  }
                </div>
              ))}
            </div>

            {selected.warnings.length > 0 && (
              <div className="mt-5">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">Warnings</h3>
                {selected.warnings.map((w) => (
                  <div key={w.user_id} className="flex items-center gap-2 py-2 px-3 bg-yellow-50 border border-yellow-100 rounded-lg mb-1">
                    <span className="text-sm text-gray-800 flex-1">{w.username}</span>
                    <Badge color="yellow">{w.count}/3 warnings</Badge>
                    <button
                      onClick={async () => { await api.clearWarnings(w.user_id, selected.id); openDetail(selected.id) }}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      Clear
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Recent messages</h3>
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {selected.recent_messages.map((m) => (
                <div key={m.id} className="text-sm border rounded-lg px-3 py-2">
                  <span className={`font-medium ${m.is_digital ? 'text-purple-600' : 'text-blue-600'}`}>{m.username}</span>
                  <span className="text-gray-400 text-xs ml-2">{new Date(m.created_at).toLocaleString()}</span>
                  <p className="text-gray-700 mt-0.5">{m.content}</p>
                </div>
              ))}
              {selected.recent_messages.length === 0 && <p className="text-sm text-gray-400">No messages yet.</p>}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      {confirm && <Confirm message={confirm.message} onConfirm={confirm.action} onCancel={() => setConfirm(null)} />}
      <div className="flex items-center gap-3 mb-5">
        <h2 className="text-lg font-semibold text-gray-900">Communities</h2>
        <input
          type="text"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="ml-auto border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 w-56"
        />
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="space-y-2">
          {communities.map((c) => (
            <div
              key={c.id}
              onClick={() => openDetail(c.id)}
              className="bg-white border rounded-xl px-4 py-3 cursor-pointer hover:border-blue-300 transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-900 truncate">{c.name}</p>
                  {c.description && <p className="text-xs text-gray-500 truncate mt-0.5">{c.description}</p>}
                </div>
                <div className="flex gap-2 flex-shrink-0 items-center">
                  <Badge color={STATUS_BADGE[c.status].color}>{STATUS_BADGE[c.status].label}</Badge>
                  <Badge color="blue">{c.real_member_count} members</Badge>
                  {c.digital_member_count > 0 && <Badge color="purple">{c.digital_member_count} AI</Badge>}
                  <Badge color="gray">{c.message_count} msgs</Badge>
                </div>
              </div>
            </div>
          ))}
          {communities.length === 0 && <p className="text-sm text-gray-400">No communities found.</p>}
        </div>
      )}
    </div>
  )
}

// ── Users ────────────────────────────────────────────────────────────────────

function Users() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<AdminUserDetail | null>(null)
  const [confirm, setConfirm] = useState<{ action: () => void; message: string } | null>(null)
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    api.adminUsers(search).then(setUsers).finally(() => setLoading(false))
  }, [search])

  useEffect(() => { load() }, [load])

  async function handleDelete(id: string, username: string) {
    setConfirm({
      message: `Permanently delete user "${username}"? This cannot be undone.`,
      action: async () => {
        await api.deleteUser(id)
        setConfirm(null)
        setSelected(null)
        load()
      },
    })
  }

  async function handleKick(userId: string, communityId: string, communityName: string) {
    setConfirm({
      message: `Remove user from "${communityName}"?`,
      action: async () => {
        await api.kickUserFromCommunity(userId, communityId)
        setConfirm(null)
        const detail = await api.adminUser(userId)
        setSelected(detail)
      },
    })
  }

  if (selected) {
    return (
      <div className="p-6">
        {confirm && <Confirm message={confirm.message} onConfirm={confirm.action} onCancel={() => setConfirm(null)} />}
        {editing && (
          <EditModal
            title="Edit user"
            fields={[
              { key: 'username', label: 'Username', required: true },
              { key: 'email', label: 'Email', type: 'email', required: true },
              { key: 'is_admin', label: 'Admin access', type: 'checkbox' },
              { key: 'new_password', label: 'Reset password', type: 'password', placeholder: 'Leave blank to keep current password' },
            ]}
            initial={{ username: selected.username, email: selected.email, is_admin: selected.is_admin, new_password: '' }}
            onSave={async (vals) => {
              const payload: Record<string, string | boolean | undefined> = {
                username: vals.username as string,
                email: vals.email as string,
                is_admin: vals.is_admin as boolean,
              }
              const pw = (vals.new_password as string).trim()
              if (pw) payload.new_password = pw
              await api.updateAdminUser(selected.id, payload as any)
              const detail = await api.adminUser(selected.id)
              setSelected(detail)
              load()
            }}
            onClose={() => setEditing(false)}
          />
        )}
        <div className="flex items-center gap-3 mb-5">
          <button onClick={() => setSelected(null)} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
          <h2 className="text-lg font-semibold text-gray-900">{selected.username}</h2>
          {selected.is_admin && <Badge color="blue">Admin</Badge>}
          {selected.is_banned && <Badge color="red">Banned</Badge>}
          <button onClick={() => setEditing(true)} className="text-sm text-blue-500 hover:text-blue-700">
            Edit
          </button>
          <button
            onClick={() => handleDelete(selected.id, selected.username)}
            className="ml-auto text-sm text-red-500 hover:text-red-700"
          >
            Delete user
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-4">
            <div className="bg-white border rounded-xl p-4 space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-gray-500">Email</span><span>{selected.email}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Joined</span><span>{new Date(selected.created_at).toLocaleDateString()}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Onboarded</span><span>{selected.onboarding_complete ? 'Yes' : 'No'}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Communities</span><span>{selected.community_count}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Messages</span><span>{selected.message_count}</span></div>
            </div>

            {selected.profile_summary && (
              <div className="bg-gray-50 border rounded-xl p-4">
                <p className="text-xs font-semibold text-gray-500 mb-1">Profile summary</p>
                <p className="text-sm text-gray-700 leading-relaxed">{selected.profile_summary}</p>
              </div>
            )}

            <div>
              <p className="text-xs font-semibold text-gray-500 mb-2">Community memberships</p>
              {selected.memberships.length === 0 && <p className="text-sm text-gray-400">No memberships.</p>}
              {selected.memberships.map((m) => (
                <div key={m.id} className="flex items-center gap-2 py-2 px-3 bg-white border rounded-lg mb-1">
                  <span className="text-sm text-gray-800 flex-1">{m.name}</span>
                  <span className="text-xs text-gray-400">{new Date(m.joined_at).toLocaleDateString()}</span>
                  <button
                    onClick={() => handleKick(selected.id, m.id, m.name)}
                    className="text-xs text-red-400 hover:text-red-600"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>

            {selected.warnings.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-500 mb-2">Moderation warnings</p>
                {selected.warnings.map((w) => (
                  <div key={w.community_id} className="flex items-center gap-2 py-2 px-3 bg-yellow-50 border border-yellow-100 rounded-lg mb-1">
                    <span className="text-sm flex-1">{w.community_name}</span>
                    <Badge color="yellow">{w.count}/3</Badge>
                    <button
                      onClick={async () => {
                        await api.clearWarnings(selected.id, w.community_id)
                        const d = await api.adminUser(selected.id)
                        setSelected(d)
                      }}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      Clear
                    </button>
                  </div>
                ))}
              </div>
            )}

            {(selected.bans.length > 0 || selected.is_banned) && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-semibold text-gray-500">Community bans</p>
                  {selected.is_banned && (
                    <button
                      onClick={async () => {
                        await api.liftGlobalBan(selected.id)
                        const d = await api.adminUser(selected.id)
                        setSelected(d)
                        load()
                      }}
                      className="text-xs text-blue-500 hover:text-blue-700 font-medium"
                    >
                      Lift global ban
                    </button>
                  )}
                </div>
                {selected.is_banned && (
                  <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-2 text-sm text-red-700">
                    This user is globally banned — they cannot join any community or use the personal agent.
                  </div>
                )}
                {selected.bans.map((b) => (
                  <div key={b.community_id} className="flex items-center gap-2 py-2 px-3 bg-red-50 border border-red-100 rounded-lg mb-1">
                    <span className="text-sm flex-1">{b.community_name}</span>
                    <span className="text-xs text-gray-400">{new Date(b.banned_at).toLocaleDateString()}</span>
                    <button
                      onClick={async () => {
                        await api.liftCommunityBan(selected.id, b.community_id)
                        const d = await api.adminUser(selected.id)
                        setSelected(d)
                      }}
                      className="text-xs text-blue-400 hover:text-blue-600"
                    >
                      Lift ban
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <p className="text-xs font-semibold text-gray-500 mb-3">Recent messages</p>
            <div className="space-y-2 max-h-[480px] overflow-y-auto">
              {selected.recent_messages.map((m) => (
                <div key={m.id} className="text-sm border rounded-lg px-3 py-2">
                  <span className="text-xs text-gray-400">{m.community_name} · {new Date(m.created_at).toLocaleString()}</span>
                  <p className="text-gray-700 mt-0.5">{m.content}</p>
                </div>
              ))}
              {selected.recent_messages.length === 0 && <p className="text-sm text-gray-400">No messages.</p>}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      {confirm && <Confirm message={confirm.message} onConfirm={confirm.action} onCancel={() => setConfirm(null)} />}
      <div className="flex items-center gap-3 mb-5">
        <h2 className="text-lg font-semibold text-gray-900">Users</h2>
        <input
          type="text"
          placeholder="Search by username or email…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="ml-auto border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 w-72"
        />
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b">
                <th className="pb-2 font-medium">Username</th>
                <th className="pb-2 font-medium">Email</th>
                <th className="pb-2 font-medium">Communities</th>
                <th className="pb-2 font-medium">Messages</th>
                <th className="pb-2 font-medium">Warnings</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Joined</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  onClick={() => api.adminUser(u.id).then(setSelected)}
                  className="border-b cursor-pointer hover:bg-blue-50 transition-colors"
                >
                  <td className="py-2.5 font-medium text-gray-900">
                    {u.username}
                    {u.is_admin && <span className="ml-1.5 text-xs text-blue-500">admin</span>}
                  </td>
                  <td className="py-2.5 text-gray-500">{u.email}</td>
                  <td className="py-2.5 text-center">{u.community_count}</td>
                  <td className="py-2.5 text-center">{u.message_count}</td>
                  <td className="py-2.5 text-center">
                    {u.warning_count > 0 ? <Badge color="yellow">{u.warning_count}</Badge> : <span className="text-gray-400">—</span>}
                  </td>
                  <td className="py-2.5">
                    {u.onboarding_complete
                      ? <Badge color="green">Active</Badge>
                      : <Badge color="gray">Onboarding</Badge>}
                  </td>
                  <td className="py-2.5 text-gray-400">{new Date(u.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {users.length === 0 && <p className="text-sm text-gray-400 mt-4">No users found.</p>}
        </div>
      )}
    </div>
  )
}

// ── Moderation ───────────────────────────────────────────────────────────────

function Moderation() {
  const [warnings, setWarnings] = useState<AdminWarning[]>([])
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    api.adminModeration().then(setWarnings).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-5">Moderation</h2>
      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : warnings.length === 0 ? (
        <p className="text-sm text-gray-400">No warnings on record.</p>
      ) : (
        <div className="space-y-2">
          {warnings.map((w) => (
            <div key={`${w.user_id}-${w.community_id}`} className="bg-white border rounded-xl px-4 py-3 flex items-center gap-4">
              <div className="flex-1">
                <span className="font-medium text-gray-900">{w.username}</span>
                <span className="text-gray-400 mx-2">in</span>
                <span className="text-gray-700">{w.community_name}</span>
              </div>
              <Badge color={w.count >= 3 ? 'red' : w.count === 2 ? 'yellow' : 'gray'}>
                {w.count}/3 warnings
              </Badge>
              <button
                onClick={async () => { await api.clearWarnings(w.user_id, w.community_id); load() }}
                className="text-xs text-gray-400 hover:text-gray-700"
              >
                Clear
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Logs ─────────────────────────────────────────────────────────────────────

function Logs() {
  const [logs, setLogs] = useState<AdminLog[]>([])
  const [filter, setFilter] = useState<'ALL' | 'ERROR' | 'WARNING' | 'INFO'>('ALL')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.adminLogs().then(setLogs).finally(() => setLoading(false))
  }, [])

  const levelColor: Record<string, string> = {
    ERROR: 'text-red-600',
    CRITICAL: 'text-red-700 font-bold',
    WARNING: 'text-yellow-600',
    INFO: 'text-blue-500',
    DEBUG: 'text-gray-400',
  }

  const filtered = filter === 'ALL' ? logs : logs.filter((l) => l.level === filter)

  return (
    <div className="p-6">
      <div className="flex items-center gap-3 mb-5">
        <h2 className="text-lg font-semibold text-gray-900">Application Logs</h2>
        <div className="ml-auto flex gap-1">
          {(['ALL', 'ERROR', 'WARNING', 'INFO'] as const).map((lvl) => (
            <button
              key={lvl}
              onClick={() => setFilter(lvl)}
              className={`text-xs px-3 py-1 rounded-full border transition-colors ${filter === lvl ? 'bg-gray-800 text-white border-gray-800' : 'text-gray-500 border-gray-200 hover:border-gray-400'}`}
            >
              {lvl}
            </button>
          ))}
        </div>
        <button
          onClick={() => { setLoading(true); api.adminLogs().then(setLogs).finally(() => setLoading(false)) }}
          className="text-xs text-blue-500 hover:text-blue-700"
        >
          Refresh
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="font-mono text-xs space-y-0.5 max-h-[600px] overflow-y-auto">
          {filtered.map((log, i) => (
            <div key={i} className={`flex gap-3 py-1 px-2 rounded hover:bg-gray-50 ${log.level === 'ERROR' || log.level === 'CRITICAL' ? 'bg-red-50' : ''}`}>
              <span className="text-gray-400 flex-shrink-0 w-36">{log.time}</span>
              <span className={`flex-shrink-0 w-16 ${levelColor[log.level] ?? 'text-gray-500'}`}>{log.level}</span>
              <span className="text-gray-400 flex-shrink-0 w-32 truncate">{log.logger}</span>
              <span className="text-gray-700 break-all">{log.message}</span>
            </div>
          ))}
          {filtered.length === 0 && <p className="text-gray-400 py-4 text-center">No log entries.</p>}
        </div>
      )}
    </div>
  )
}

// ── Metrics ──────────────────────────────────────────────────────────────────

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m ${s}s`
  return `${m}m ${s}s`
}

function Metrics() {
  const [data, setData] = useState<MetricsSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  function load() {
    setLoading(true)
    setError(null)
    api.metrics().then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const agents = data ? Object.entries(data.agents) : []

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-900">Metrics</h2>
        <button onClick={load} className="ml-auto text-xs text-blue-500 hover:text-blue-700">Refresh</button>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-500">{error}</p>}

      {data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Uptime" value={formatUptime(data.uptime_seconds)} />
            <StatCard label="Agents tracked" value={agents.length} />
            <StatCard
              label="Total calls"
              value={agents.reduce((sum, [, a]) => sum + a.calls, 0)}
            />
            <StatCard
              label="Total errors"
              value={agents.reduce((sum, [, a]) => sum + a.errors, 0)}
            />
          </div>

          {agents.length === 0 ? (
            <p className="text-sm text-gray-400">No agent data recorded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b">
                    <th className="pb-2 font-medium">Agent</th>
                    <th className="pb-2 font-medium text-right">Calls</th>
                    <th className="pb-2 font-medium text-right">Errors</th>
                    <th className="pb-2 font-medium text-right">Error rate</th>
                    <th className="pb-2 font-medium text-right">Tool calls</th>
                    <th className="pb-2 font-medium text-right">Avg latency</th>
                    <th className="pb-2 font-medium text-right">p50</th>
                    <th className="pb-2 font-medium text-right">p95</th>
                    <th className="pb-2 font-medium text-right">p99</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map(([name, a]) => (
                    <tr key={name} className="border-b hover:bg-gray-50">
                      <td className="py-2.5 font-medium text-gray-900">{name}</td>
                      <td className="py-2.5 text-right text-gray-700">{a.calls}</td>
                      <td className="py-2.5 text-right">
                        {a.errors > 0
                          ? <span className="text-red-600 font-medium">{a.errors}</span>
                          : <span className="text-gray-400">0</span>}
                      </td>
                      <td className="py-2.5 text-right">
                        {a.error_rate > 0
                          ? <Badge color={a.error_rate > 0.1 ? 'red' : 'yellow'}>{(a.error_rate * 100).toFixed(1)}%</Badge>
                          : <span className="text-gray-400">0%</span>}
                      </td>
                      <td className="py-2.5 text-right text-gray-700">{a.tool_calls}</td>
                      <td className="py-2.5 text-right text-gray-700">{a.latency_avg_ms} ms</td>
                      <td className="py-2.5 text-right text-gray-500">{a.latency_p50_ms} ms</td>
                      <td className="py-2.5 text-right text-gray-500">{a.latency_p95_ms} ms</td>
                      <td className="py-2.5 text-right text-gray-500">{a.latency_p99_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Admin shell ───────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'communities', label: 'Communities' },
  { id: 'users', label: 'Users' },
  { id: 'moderation', label: 'Moderation' },
  { id: 'logs', label: 'Logs' },
  { id: 'metrics', label: 'Metrics' },
]

export default function Admin() {
  const [tab, setTab] = useState<Tab>('dashboard')
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  useEffect(() => {
    if (!user?.is_admin) navigate('/', { replace: true })
  }, [user])

  if (!user?.is_admin) return null

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Top bar */}
      <header className="bg-white border-b px-6 py-3 flex items-center gap-4">
        <span className="font-bold text-gray-900">Admin Panel</span>
        <span className="text-xs text-gray-400">community.ai</span>
        <nav className="flex gap-1 ml-6">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-1.5 rounded-lg text-sm transition-colors ${
                tab === t.id ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <button onClick={() => navigate('/community')} className="text-sm text-blue-600 hover:text-blue-800">
            ← App
          </button>
          <button onClick={() => { logout(); navigate('/login') }} className="text-sm text-gray-400 hover:text-gray-700">
            Sign out
          </button>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1">
        {tab === 'dashboard' && <Dashboard />}
        {tab === 'communities' && <Communities />}
        {tab === 'users' && <Users />}
        {tab === 'moderation' && <Moderation />}
        {tab === 'logs' && <Logs />}
        {tab === 'metrics' && <Metrics />}
      </main>
    </div>
  )
}
