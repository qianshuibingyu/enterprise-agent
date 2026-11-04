export type AttachmentMetadata = {
  id: number
  original_filename: string
  media_type: string
  size_bytes: number
}

export type ChannelAccount = {
  id: number
  owner_user_id: number
  channel_type: string
  status: string
  external_account_id?: string | null
  test_only?: boolean
}

export type CurrentUser = {
  id: number
  username: string
  role: string
}

export type TransferTarget = {
  id: number
  username: string
  role: 'sales'
}

export type Inquiry = {
  id: number
  customer_contact: string
  customer_nickname: string
  display_text: string
  display_excerpt: string
  content_format: 'text/plain'
  content_sanitized: boolean
  content_truncated: boolean
  source_channel_account_id: number
  status: string
  handling_status: 'pending' | 'processed' | 'ignored'
  assigned_sales_user_id: number | null
  created_at: string | null
  updated_at: string | null
  timeline: InquiryEvent[]
  timeline_complete: boolean
  attachments: AttachmentMetadata[]
}

export type InquiryEvent = {
  id: number
  event_type: string
  actor_user_id: number | null
  from_status: string | null
  to_status: string | null
  target_user_id: number | null
  occurred_at: string
  created_at: string
}

export type InquiryStatusCounts = {
  new: number
  assigned: number
}

export type InquiryHandlingStatusCounts = {
  pending: number
  processed: number
  ignored: number
}

export type InternalAnalysis = {
  mode: 'read_only' | 'guidance'
  read_only: boolean
  test_only: string
  stage_source?: string
  event_source?: string
  event_history_available?: boolean
  actor_id?: number
  pending_message_count?: number
  inquiries_by_status?: InquiryStatusCounts
  inquiries_by_handling_status?: InquiryHandlingStatusCounts
  my_transfers?: Array<{
    inquiry_id: number
    customer_nickname: string
    status: string
    assigned_sales_user_id: number | null
    updated_at: string | null
    current_stage: string
    recent_event: {
      type: string
      occurred_at: string
      source: string
      event_history_available: boolean
    } | null
  }>
  channel_statuses?: Array<{
    channel_account_id: number
    channel_type: string
    status: string
    is_abnormal: boolean
  }>
  page?: string
  message?: string
}

export type Message = {
  id: number
  channel_account_id: number
  channel_type: string
  provider: string
  external_message_id: string
  direction: string
  ingestion_status: string
  handling_status: 'pending' | 'processed' | 'ignored'
  occurred_at: string
  created_at: string | null
  display_text: string
  display_excerpt: string
  content_format: 'text/plain'
  content_sanitized: boolean
  content_truncated: boolean
  attachments: AttachmentMetadata[]
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
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
      // Keep the status-based message when the response is not JSON.
    }
    throw new ApiError(response.status, message)
  }

  return response.json() as Promise<T>
}

export const inboxApi = {
  getCurrentUser: () => getJson<CurrentUser>('/auth/me'),
  getAccounts: () => getJson<ChannelAccount[]>('/api/channel-accounts'),
  getMessages: () => getJson<Message[]>('/api/messages'),
  getInquiries: () => getJson<Inquiry[]>('/api/inquiries'),
  getInquiry: (id: number) => getJson<Inquiry>(`/api/inquiries/${id}`),
  getOutlookMessages: (accountId: number, count = 50) =>
    getJson<{
      messages: Array<{ id: number; created: boolean }>
      total: number
      created: number
      duplicates: number
    } | Array<{ id: number; created: boolean }>>(`/api/integrations/outlook/accounts/${accountId}/messages?count=${count}`),
  getInternalAnalysis: () => getJson<InternalAnalysis>('/api/internal-analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation: 'read' }),
  }),
  getTransferTargets: () => getJson<TransferTarget[]>('/api/inquiry-transfer-targets'),
  getCsrf: async () => {
    const result = await getJson<{ csrf_token: string }>('/auth/csrf', {
      headers: { Origin: window.location.origin },
    })
    return result
  },
  logout: async (csrfToken: string) => {
    await getJson<void>('/auth/logout', {
      method: 'POST',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    })
  },
  transferInquiry: (inquiryId: number, salesUserId: number, csrfToken: string) =>
    getJson<Inquiry>(`/api/inquiries/${inquiryId}/transfer`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ sales_user_id: salesUserId }),
    }),
  updateInquiryHandling: (inquiryId: number, action: 'processed' | 'ignored', csrfToken: string) =>
    getJson<Inquiry>(`/api/inquiries/${inquiryId}/action`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ action }),
    }),
  updateMessageHandling: (messageId: number, action: 'processed' | 'ignored', csrfToken: string) =>
    getJson<Message>(`/api/messages/${messageId}/action`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ action }),
    }),
}
