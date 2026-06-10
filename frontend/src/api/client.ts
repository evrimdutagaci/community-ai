import { useAuthStore, type User } from '../store/auth'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().token
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export type CommunityStatus = 'ACTIVE' | 'CANDIDATE' | 'INACTIVE' | 'ARCHIVED'

export interface Announcement {
  id: string
  title: string
  description: string | null
  event_url: string | null
  source: string
  announced_date: string
}

export interface CommunityInfo {
  id: string
  name: string
  description: string
  status: CommunityStatus
  members: { id: string; username: string; is_digital: boolean }[]
}

export interface CommunityStub {
  id: string
  name: string
  description: string
  status: CommunityStatus
}

export const api = {
  register: (data: { email: string; username: string; password: string }) =>
    request<{ access_token: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  login: (data: { email: string; password: string }) =>
    request<{ access_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  me: () => request<User>('/auth/me'),

  myCommunities: () => request<CommunityStub[]>('/communities/memberships'),

  myCommunity: (communityId?: string) =>
    request<CommunityInfo>(
      communityId ? `/communities/mine?community_id=${communityId}` : '/communities/mine'
    ),

  leaveCommunity: (communityId: string) =>
    request<{ status: string }>('/communities/leave', {
      method: 'POST',
      body: JSON.stringify({ community_id: communityId }),
    }),

  startCommunitySearch: () =>
    request<{ status: string }>('/communities/start-search', { method: 'POST' }),

  getAnnouncements: (communityId: string) =>
    request<Announcement[]>(`/communities/${communityId}/announcements`),

  makeAdmin: (secret: string) =>
    request<{ status: string; username: string }>(`/auth/make-admin?secret=${encodeURIComponent(secret)}`, { method: 'POST' }),

  updateProfile: (data: { username: string }) =>
    request<User>('/auth/profile', { method: 'PATCH', body: JSON.stringify(data) }),

  changePassword: (data: { current_password: string; new_password: string }) =>
    request<{ status: string }>('/auth/change-password', { method: 'POST', body: JSON.stringify(data) }),

  // Admin endpoints
  updateAdminCommunity: (id: string, data: { name?: string; description?: string; location?: string; status?: string }) =>
    request<{ status: string; name: string; description: string | null }>(`/admin/communities/${id}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),

  updateAdminUser: (id: string, data: { username?: string; email?: string; is_admin?: boolean; new_password?: string }) =>
    request<{ status: string }>(`/admin/users/${id}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),

  adminStats: () => request<AdminStats>('/admin/stats'),
  adminCommunities: (search = '') => request<AdminCommunity[]>(`/admin/communities?search=${encodeURIComponent(search)}`),
  adminCommunity: (id: string) => request<AdminCommunityDetail>(`/admin/communities/${id}`),
  deleteCommunity: (id: string) => request<{ status: string }>(`/admin/communities/${id}`, { method: 'DELETE' }),
  adminUsers: (search = '') => request<AdminUser[]>(`/admin/users?search=${encodeURIComponent(search)}`),
  adminUser: (id: string) => request<AdminUserDetail>(`/admin/users/${id}`),
  deleteUser: (id: string) => request<{ status: string }>(`/admin/users/${id}`, { method: 'DELETE' }),
  kickUserFromCommunity: (userId: string, communityId: string) =>
    request<{ status: string }>(`/admin/users/${userId}/kick?community_id=${communityId}`, { method: 'POST' }),
  clearWarnings: (userId: string, communityId: string) =>
    request<{ status: string }>(`/admin/warnings/${userId}/${communityId}`, { method: 'DELETE' }),

  liftCommunityBan: (userId: string, communityId: string) =>
    request<{ status: string }>(`/admin/bans/${userId}/${communityId}`, { method: 'DELETE' }),

  liftGlobalBan: (userId: string) =>
    request<{ status: string }>(`/admin/users/${userId}/lift-ban`, { method: 'POST' }),
  adminModeration: () => request<AdminWarning[]>('/admin/moderation'),
  adminLogs: () => request<AdminLog[]>('/admin/logs'),
  metrics: () => request<MetricsSnapshot>('/metrics'),
}

export interface AdminStats {
  users: { total: number; digital: number }
  communities: { total: number }
  messages: { total: number; today: number; dms: number }
  warnings: { active: number }
}

export interface AdminCommunity {
  id: string; name: string; description: string
  real_member_count: number; digital_member_count: number
  message_count: number; status: CommunityStatus; created_at: string
}

export interface AdminCommunityDetail extends AdminCommunity {
  members: { id: string; username: string; is_digital: boolean; email: string }[]
  recent_messages: { id: string; user_id: string; username: string; is_digital: boolean; content: string; created_at: string }[]
  warnings: { user_id: string; username: string; count: number }[]
  status_override: CommunityStatus | null
}

export interface AdminUser {
  id: string; username: string; email: string; is_admin: boolean
  onboarding_complete: boolean; community_count: number
  message_count: number; warning_count: number; created_at: string
}

export interface AdminUserDetail extends AdminUser {
  profile_summary: string | null; is_digital: boolean; is_banned: boolean
  memberships: { id: string; name: string; joined_at: string }[]
  warnings: { community_id: string; community_name: string; count: number }[]
  bans: { community_id: string; community_name: string; banned_at: string }[]
  recent_messages: { id: string; community_name: string; content: string; created_at: string }[]
}

export interface AdminWarning {
  user_id: string; username: string; community_id: string; community_name: string; count: number
}

export interface AdminLog {
  time: string; level: string; logger: string; message: string; exc: string | null
}

export interface AgentMetrics {
  calls: number; errors: number; error_rate: number; tool_calls: number
  latency_avg_ms: number; latency_p50_ms: number; latency_p95_ms: number; latency_p99_ms: number
}

export interface MetricsSnapshot {
  uptime_seconds: number
  agents: Record<string, AgentMetrics>
}
