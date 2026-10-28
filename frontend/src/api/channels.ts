export type ChannelCapabilities = {
  inbound: boolean
  outbound: boolean
  realtime: boolean
  webhook: boolean
  polling: boolean
  attachments: boolean
  requires_public_endpoint: boolean
}

export type ChannelDescriptor = {
  channel_type: string
  provider: string
  display_name: string
  authorization_owner: string
  ingress_kind: string
  capabilities: ChannelCapabilities
  test_only: boolean
  legacy: boolean
  status_values: string[]
}

export type ChannelAccount = {
  id: number
  owner_user_id: number
  channel_type: string
  status: string
  external_account_id: string | null
  test_only: boolean
}

export class ChannelApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ChannelApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // Preserve the status-based error for non-JSON responses.
    }
    throw new ChannelApiError(response.status, message)
  }

  return response.json() as Promise<T>
}

export const channelsApi = {
  list: () => request<ChannelDescriptor[]>('/api/channels'),
  startGmailAuthorization: (accountId: number, csrfToken: string) =>
    request<{ channel_account_id: number; authorization_url: string }>(
      `/api/integrations/gmail/authorize/start?account_id=${accountId}`,
      {
        method: 'POST',
        headers: {
          Origin: window.location.origin,
          'X-CSRF-Token': csrfToken,
        },
      },
    ),
  accounts: () => request<ChannelAccount[]>('/api/channels/accounts'),
  authorize: (channelType: string, csrfToken: string) =>
    request(`/api/channels/${encodeURIComponent(channelType)}/authorize`, {
      method: 'POST',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
  revoke: (accountId: number, csrfToken: string) =>
    request(`/api/channels/accounts/${accountId}/revoke`, {
      method: 'POST',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
}
