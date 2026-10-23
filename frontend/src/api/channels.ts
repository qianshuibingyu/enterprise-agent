export type ChannelStatus =
  | 'not_connected'
  | 'authorizing'
  | 'connected'
  | 'blocked'
  | 'error'
  | 'revoked'

export interface ChannelDescriptor {
  channel_type: string
  display_name: string
  guide: string
  real_integration: boolean
  blocked_reason: string | null
  test_provider_available: boolean
}

export interface ChannelAccount {
  id: number
  owner_user_id: number
  channel_type: string
  status: ChannelStatus
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'include',
    ...init,
  })
  if (!response.ok) {
    throw new Error(`channel request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function listChannels(): Promise<ChannelDescriptor[]> {
  return request('/api/channels')
}

export function listChannelAccounts(): Promise<ChannelAccount[]> {
  return request('/api/channels/accounts')
}

async function csrfToken(): Promise<string> {
  const response = await fetch('/auth/csrf', {
    credentials: 'include',
    headers: { Origin: window.location.origin },
  })
  if (!response.ok) throw new Error(`csrf request failed: ${response.status}`)
  const body = (await response.json()) as { csrf_token: string }
  return body.csrf_token
}

export async function startTestAuthorization(channelType: string, accountId: number): Promise<{
  status: ChannelStatus
  authorization_url: string
  state: string
  test_only: true
}> {
  const csrf = await csrfToken()
  return request(`/api/channels/${channelType}/accounts/${accountId}/authorize?test_mode=true`, {
    method: 'POST',
    headers: {
      Origin: window.location.origin,
      'X-CSRF-Token': csrf,
    },
  })
}
