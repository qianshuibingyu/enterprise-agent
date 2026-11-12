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

export type ConnectionStatus =
  | 'not_ready'
  | 'awaiting_authorization'
  | 'connected_pending_inbound'
  | 'verified_inbound'
  | 'blocked'
  | 'system_error'
  | 'revoked'

export type ChannelType = 'gmail' | 'outlook' | 'whatsapp'

export type ChannelAccount = {
  id: number
  owner_user_id: number
  channel_type: ChannelType
  status: ConnectionStatus | string
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
  createWhatsAppAccount: (csrfToken: string) =>
    request<ChannelAccount>('/api/channels/whatsapp/accounts', {
      method: 'POST',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
  createGmailAccount: (csrfToken: string) =>
    request<ChannelAccount>('/api/channels/gmail/accounts', {
      method: 'POST',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
  startWhatsAppPairing: (accountId: number, csrfToken: string) =>
    request<{ channel_account_id: number; qr: string; expires_at: string; state?: string; detail?: string | null; test_only: boolean }>(
      `/api/integrations/whatsapp/accounts/${accountId}/pair/start`,
      {
        method: 'POST',
        headers: {
          Origin: window.location.origin,
          'X-CSRF-Token': csrfToken,
        },
      },
    ),
  getWhatsAppStatus: (accountId: number) =>
    request<{ channel_account_id: number; state: string; qr?: string; expires_at?: string; external_account_id: string | null; detail: string | null; status?: string }>(
      `/api/integrations/whatsapp/accounts/${accountId}/pair/status`,
    ),
  disconnectWhatsApp: (accountId: number, csrfToken: string) =>
    request<{ channel_account_id: number; state: string; external_account_id: string | null; detail: string | null }>(
      `/api/integrations/whatsapp/accounts/${accountId}/disconnect`,
      {
        method: 'POST',
        headers: {
          Origin: window.location.origin,
          'X-CSRF-Token': csrfToken,
        },
      },
    ),
  createOutlookAccount: (csrfToken: string) =>
    request<ChannelAccount>('/api/channels/outlook/accounts', {
      method: 'POST',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
  startOutlookAuthorization: (accountId: number, csrfToken: string) =>
    request<{ channel_account_id: number; authorization_url: string }>(
      `/api/integrations/outlook/authorize/start?account_id=${accountId}`,
      {
        method: 'POST',
        headers: {
          Origin: window.location.origin,
          'X-CSRF-Token': csrfToken,
        },
      },
    ),
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
    request<{ channel_account_id: number; channel_type: ChannelType; status: ConnectionStatus; test_only: boolean }>(`/api/channels/accounts/${accountId}/revoke`, {
      method: 'POST',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
}
