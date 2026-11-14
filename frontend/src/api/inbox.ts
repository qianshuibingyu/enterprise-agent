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

export type EmployeeRecord = {
  id: number
  username: string
  full_name: string | null
  role: string
  department: string | null
  manager_overlay_enabled: boolean
  manager_grants: { target_user_id: number; department: string; permission: string }[]
  is_active: boolean
  must_change_password: boolean
  department_grants: string[]
  channel_preauthorizations: string[]
  capability_grants: string[]
}

export type AdminChannelAccount = {
  id: number
  owner_user_id: number
  channel_type: string
  external_account_id: string | null
  status: string
  history_access_revoked: boolean
}

export type ChannelOwnerTransferResult = {
  status: string
  owner_user_id: number
  owner_username: string
  transferred: { id: number; channel_type: string; previous_owner_user_id: number }[]
  skipped: { id: number; channel_type: string; reason: string }[]
  retired_shells: { id: number; channel_type: string; history_messages_moved: number; deleted: boolean }[]
  preauthorizations_granted: string[]
}

export type CurrentUser = {
  id: number
  username: string
  role: string
  department: string | null
  must_change_password: boolean
}

export type TransferTarget = {
  id: number
  username: string
  full_name?: string | null
  name?: string | null
  role: 'sales'
}

export type Inquiry = {
  id: number
  contact_sources: Array<{
    raw_customer_contact: string | null
    normalized_customer_contact: string | null
    contact_identity_state: 'certain' | 'forwarded' | 'identity_uncertain' | 'needs_manual_review' | 'unsupported'
    contact_identity_kind: 'email' | 'whatsapp' | null
    customer_nickname: string | null
    channel_account_id?: number | null
    channel_type: string | null
  }>
  /** 非管理员可见清洗正文；管理员仅收到联系人脱敏后的概述和状态元数据。 */
  messages: Array<{
    id: number
    channel_account_id?: number
    channel_account_external_id?: string | null
    channel_type: string
    provider?: string
    external_message_id?: string
    direction: string
    handling_status: 'pending' | 'processed' | 'ignored'
    occurred_at: string
    safe_text: string | null
    safe_text_truncated: boolean
    content_state: 'ready' | 'revoked' | 'hidden'
    safe_content_status?: 'ready' | 'revoked'
    overview_status: 'pending' | 'ready' | 'failed' | 'not_generated' | 'not_applicable_revoked' | null
    overview_text: string | null
  }>
  source_channel_account_id: null
  status: string
  business_type: 'inquiry' | 'after_sales' | null
  handling_status: 'pending' | 'processed' | 'ignored'
  assigned_sales_user_id: number | null
  assigned_sales_name?: string | null
  assigned_sales_username?: string | null
  /** 转交人：点「分配」的那个运营账号，与负责人不同。 */
  transferred_by_name?: string | null
  transferred_by_username?: string | null
  transferred_at?: string | null
  last_activity_at: string | null
  lifecycle_stage: 'unknown' | 'active' | 'archived_silent' | 'purge_due'
  created_at: string | null
  updated_at: string | null
  timeline: InquiryEvent[]
  timeline_complete: boolean
  attachments: []
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
  generated_at?: string
  mutation_performed?: false
  write_operations_performed?: 0
  query_scope?: 'current_user_authorized_objects' | 'company_wide_inquiry_inspection'
  test_only: string
  stage_source?: string
  event_source?: string
  event_history_available?: boolean
  actor_id?: number
  actions?: Array<{ operation: 'create' | 'assign' | 'update' | 'send'; page: string; label: string }>
  pending_message_count?: number
  pending_inbound_message_count?: number
  pending_contact_count?: number
  inquiries_by_lifecycle_stage?: Record<'unknown' | 'active' | 'archived_silent' | 'purge_due', number>
  messages_by_link_state?: Record<'pending' | 'linked' | 'unmatched' | 'manual_review' | 'not_linkable', number>
  unlinked_messages?: Array<{
    id: number
    channel_account_id?: number
    provider?: string
    external_message_id?: string
    identity_state: string
    link_state: string
    occurred_at: string
  }>
  recent_events?: Array<{
    inquiry_id: number
    event_type: string
    occurred_at: string
    actor_user_id: number | null
  }>
  messages_needing_manual_review?: Array<{
    id: number
    provider?: string
    external_message_id?: string
    link_state: string
    identity_state: string
    occurred_at: string
  }>
  inquiries_by_status?: InquiryStatusCounts
  inquiries_by_handling_status?: InquiryHandlingStatusCounts
  my_transfers?: Array<{
    inquiry_id: number
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
    channel_account_id?: number
    channel_type: string
    status: string
    is_abnormal: boolean
  }>
  page?: string
  message?: string
}

export type InquiryLinkCandidates = {
  message_id: number
  match_state: 'linked' | 'missing_identity' | 'unsupported_identity' | 'manual_confirmation_required' | 'none' | 'unique' | 'multiple'
  identity_state?: 'certain' | 'forwarded' | 'identity_uncertain' | 'needs_manual_review' | 'unsupported'
  identity_kind?: 'email' | 'whatsapp_phone'
  requires_identity_confirmation?: boolean
  items: Array<Pick<Inquiry, 'id' | 'status' | 'handling_status'> & {
    customer_contact?: string
    customer_nickname?: string
    contact_identity_kind?: 'email' | 'whatsapp' | null
    contact_identity_state?: Message['contact_identity_state']
  }>
}

/** Operator-managed WhatsApp group -> customer phone binding.
 *  Only a human creates/changes/removes these; the automatic inquiry-linking
 *  pipeline never reads or writes them. */
export type WhatsappGroupBinding = {
  id: number
  group_jid: string
  normalized_phone: string
  raw_phone: string | null
  channel_account_id: number | null
  bound_by: string | null
  note: string | null
  created_at: string | null
  updated_at: string | null
}

/** A phone number already seen on the operator's authorized WhatsApp accounts.
 *  This is a picker list only, never a system guess about group ownership. */
export type WhatsappPhoneCandidate = {
  normalized_phone: string
  customer_contact: string | null
  customer_nickname: string | null
  channel_account_id: number | null
  last_seen_at: string | null
  message_count: number
}

export type RefetchCheck = {
  account_id: number
  channel_type: string
  ready: boolean
  failure_kind: string | null
  /** ok = 链路可用；not_ready = 尚未关联，非故障；action_required = 需要处理。 */
  severity: 'ok' | 'action_required' | 'not_ready'
  recommended_action: string
  error_class?: string | null
  network?: { kind: string; label: string; host: string } | null
  history_available?: boolean
  steps: Array<{ name: string; ok: boolean; detail: string }>
}

export type Message = {
  id: number
  channel_account_id: number
  channel_type: string
  is_website_form?: boolean
  provider: string
  external_message_id: string
  customer_contact: string | null
  normalized_customer_contact: string | null
  original_sender_contact: string | null
  contact_identity_state: 'certain' | 'forwarded' | 'identity_uncertain' | 'needs_manual_review' | 'unsupported'
  contact_identity_kind: 'email' | 'whatsapp' | null
  customer_nickname: string | null
  direction: string
  ingestion_status: string
  handling_status: 'pending' | 'processed' | 'ignored'
  inquiry_id: number | null
  link_state: 'pending' | 'linked' | 'manual_review' | 'unmatched' | 'not_linkable'
  occurred_at: string
  created_at: string | null
  display_text: string
  display_excerpt: string
  content_format: 'text/plain'
  content_sanitized: boolean
  content_truncated: boolean
  /** revoked = 客户双端删除/撤回，没有可处理的正文。 */
  content_state: 'ready' | 'revoked'
  overview: {
    status: 'pending' | 'ready' | 'failed'
    text: string | null
    failure_code: string | null
    retry_count: number
    provider_name: string | null
    model_name: string | null
    prompt_version: string
  } | null
  attachments: AttachmentMetadata[]
}

export type MessageBulkActionResult = {
  action: 'processed' | 'ignored'
  updated_message_ids: number[]
  updated_inquiry_ids: number[]
  skipped: Array<{
    message_id: number | null
    reason: string
    detail: string
    inquiry_id?: number
  }>
}

export type OperationLog = {
  id: number
  actor_name: string
  operation_name: string
  object_type: string
  object_id: number | null
  result: 'success' | 'failure' | 'timeout'
  detail: string | null
  created_at: string
}

export type PagedResponse<T> = {
  items: T[]
  page: number
  page_size: number
  has_more: boolean
  total_count?: number
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let csrfTokenCache: string | null = null

/** Call after logout / session rotation so the next write fetches a fresh token. */
export function clearCsrfCache(): void {
  csrfTokenCache = null
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
      else if (Array.isArray(body.detail)) {
        const issues = body.detail
          .map((item: { loc?: unknown[]; msg?: unknown }) => {
            const location = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
            const detail = typeof item.msg === 'string' ? item.msg : ''
            return [location, detail].filter(Boolean).join(': ')
          })
          .filter(Boolean)
        if (issues.length > 0) message = `请求参数未通过校验：${issues.join('；')}`
      }
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new ApiError(response.status, message)
  }

  // POST /auth/logout answers 204 with no body; parsing it as JSON would throw
  // and make every successful logout look like a failure.
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const inboxApi = {
  getCurrentUser: () => getJson<CurrentUser>('/auth/me'),
  getEmployees: () => getJson<EmployeeRecord[]>('/auth/admin/users'),
  createEmployee: (body: { full_name: string; username: string; role: string; department: string; manager_overlay_enabled?: boolean; temporary_password: string }, csrfToken: string) =>
    getJson<EmployeeRecord>('/auth/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: window.location.origin, 'X-CSRF-Token': csrfToken }, body: JSON.stringify(body),
    }),
  mapEmployee: (userId: number, body: { role: string; department: string | null; manager_overlay_enabled?: boolean; full_name?: string }, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json', Origin: window.location.origin, 'X-CSRF-Token': csrfToken }, body: JSON.stringify(body),
    }),
  grantManagerPermission: (managerId: number, userId: number, department: string, permission: string, csrfToken: string) =>
    getJson(`/auth/admin/managers/${managerId}/users/${userId}/grants`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: window.location.origin, 'X-CSRF-Token': csrfToken }, body: JSON.stringify({ department, permission }),
    }),
  revokeManagerPermission: (managerId: number, userId: number, permission: string, csrfToken: string) =>
    getJson(`/auth/admin/managers/${managerId}/users/${userId}/grants/${encodeURIComponent(permission)}`, {
      method: 'DELETE', headers: { Origin: window.location.origin, 'X-CSRF-Token': csrfToken },
    }),
  grantDepartment: (userId: number, department: string, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}/department-grants`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: window.location.origin, 'X-CSRF-Token': csrfToken }, body: JSON.stringify({ department }),
    }),
  revokeDepartment: (userId: number, department: string, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}/department-grants/${encodeURIComponent(department)}`, {
      method: 'DELETE', headers: { Origin: window.location.origin, 'X-CSRF-Token': csrfToken },
    }),
  grantChannel: (userId: number, channel_type: string, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}/channel-preauthorizations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: window.location.origin, 'X-CSRF-Token': csrfToken }, body: JSON.stringify({ channel_type }),
    }),
  revokeChannel: (userId: number, channelType: string, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}/channel-preauthorizations/${encodeURIComponent(channelType)}`, {
      method: 'DELETE', headers: { Origin: window.location.origin, 'X-CSRF-Token': csrfToken },
    }),
  resetEmployeePassword: (userId: number, temporary_password: string, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}/password-reset`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: window.location.origin, 'X-CSRF-Token': csrfToken }, body: JSON.stringify({ temporary_password }),
    }),
  deactivateEmployee: (userId: number, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}/deactivate`, {
      method: 'POST', headers: { Origin: window.location.origin, 'X-CSRF-Token': csrfToken },
    }),
  reactivateEmployee: (userId: number, csrfToken: string) =>
    getJson(`/auth/admin/users/${userId}/reactivate`, {
      method: 'POST', headers: { Origin: window.location.origin, 'X-CSRF-Token': csrfToken },
    }),
  listAdminChannelAccounts: () => getJson<AdminChannelAccount[]>('/auth/admin/channel-accounts'),
  regrantChannelHistory: (accountId: number, csrfToken: string) =>
    getJson(`/auth/admin/channel-accounts/${accountId}/history-access`, {
      method: 'POST', headers: { Origin: window.location.origin, 'X-CSRF-Token': csrfToken },
    }),
  transferChannelAccountsOwner: (accountIds: number[], ownerUserId: number, csrfToken: string) =>
    getJson<ChannelOwnerTransferResult>('/auth/admin/channel-accounts/transfer-owner', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Origin: window.location.origin, 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ account_ids: accountIds, owner_user_id: ownerUserId }),
    }),
  checkChannelRefetch: (accountId: number) =>
    getJson<RefetchCheck>(`/api/channel-accounts/${accountId}/refetch-check`),
  getAccounts: () => getJson<ChannelAccount[]>('/api/channel-accounts'),
  getMessages: (params = '') => getJson<PagedResponse<Message>>(`/api/messages${params}`),
  getMessage: (id: number) => getJson<Message>(`/api/messages/${id}`),
  getInquiries: (params = '') => getJson<PagedResponse<Inquiry>>(`/api/inquiries${params}`),
  getInquiry: (id: number) => getJson<Inquiry>(`/api/inquiries/${id}`),
  getOperationLogs: (inquiryId?: number) => getJson<OperationLog[]>(
    `/api/operation-logs?limit=100${inquiryId === undefined ? '' : `&inquiry_id=${inquiryId}`}`,
  ),
  getMessageContent: (id: number) => getJson<{
    message_id: number
    channel_type: string
    provider: string
    external_message_id: string
    direction: string
    occurred_at: string
    source: {
      kind: 'cached_safe_text' | 'provider_refetch'
      provider: string
      external_message_id: string
      live_refetch: boolean
      fallback_reason: string | null
      authoritative: boolean
      refetch_status: 'refreshed' | 'snapshot'
      snapshot_at: string | null
    }
    raw_content_exposed: false
    content_state: 'ready' | 'revoked'
    parsed_content: {
      display_text: string
      display_excerpt: string
      content_format: 'text/plain'
      content_sanitized: boolean
      content_truncated: boolean
      content_state: 'ready' | 'revoked'
    }
    preview_text: string
    full_text: string
    can_expand: boolean
    attachments: AttachmentMetadata[]
  }>(`/api/messages/${id}/content`),
  getMessageInquiryCandidates: (messageId: number) =>
    getJson<InquiryLinkCandidates>(`/api/messages/${messageId}/inquiry-candidates`, {
      signal: AbortSignal.timeout(15000),
    }),
  linkMessageToInquiry: (inquiryId: number, messageId: number, csrfToken: string, confirmIdentity = false) =>
    getJson<Inquiry>(`/api/inquiries/${inquiryId}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ message_id: messageId, confirm_identity: confirmIdentity }),
    }),
  getMessageProviderAction: (id: number) => getJson<{
    supported: boolean
    channel_type: string
    action: 'open_message' | 'open_chat' | 'open_inbox' | 'none'
    url: string | null
    /** HTTP fallback when the app scheme cannot be launched on this machine. */
    web_url: string | null
    reason: string | null
  }>(`/api/messages/${id}/provider-action`),
  getOutlookMessages: (accountId: number, count = 50) =>
    getJson<{
      messages: Array<{ id: number; created: boolean }>
      total: number
      created: number
      duplicates: number
      links_repaired?: number
    } | Array<{ id: number; created: boolean }>>(`/api/integrations/outlook/accounts/${accountId}/messages?count=${count}`),
  getInternalAnalysis: () => getJson<InternalAnalysis>('/api/internal-analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation: 'read' }),
  }),
  getTransferTargets: () => getJson<TransferTarget[]>('/api/inquiry-transfer-targets'),
  /** The backend returns the session-bound double-submit token, so one fetch
   *  per page session is enough. Previously every write awaited an extra RTT. */
  getCsrf: async () => {
    if (csrfTokenCache !== null) return { csrf_token: csrfTokenCache }
    const result = await getJson<{ csrf_token: string }>('/auth/csrf', {
      headers: { Origin: window.location.origin },
    })
    csrfTokenCache = result.csrf_token
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
  transferInquiry: (inquiryId: number, salesUserId: number, businessType: 'inquiry' | 'after_sales', csrfToken: string) =>
    getJson<Inquiry>(`/api/inquiries/${inquiryId}/transfer`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ sales_user_id: salesUserId, business_type: businessType }),
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
  retryMessageOverview: (messageId: number, csrfToken: string) =>
    getJson<Message>(`/api/messages/${messageId}/overview/retry`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
  reactivateInquiry: (inquiryId: number, csrfToken: string) =>
    getJson<Inquiry>(`/api/inquiries/${inquiryId}/reactivate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
  restoreMessage: (messageId: number, csrfToken: string) =>
    getJson<Message>(`/api/messages/${messageId}/archive/restore`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
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
  bulkUpdateMessageHandling: (messageIds: number[], action: 'processed' | 'ignored', csrfToken: string) =>
    getJson<MessageBulkActionResult>('/api/messages/bulk-action', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ message_ids: messageIds, action }),
    }),
  getWhatsappGroupBindings: () =>
    getJson<WhatsappGroupBinding[]>('/api/whatsapp-group-bindings'),
  getWhatsappPhoneCandidates: () =>
    getJson<WhatsappPhoneCandidate[]>('/api/whatsapp-phone-candidates', {
      signal: AbortSignal.timeout(15000),
    }),
  bindWhatsappGroup: (groupJid: string, phone: string, csrfToken: string, note?: string) =>
    getJson<WhatsappGroupBinding>('/api/whatsapp-group-bindings', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ group_jid: groupJid, phone, note: note || null }),
    }),
  unbindWhatsappGroup: (bindingId: number, csrfToken: string) =>
    getJson<{ ok: boolean }>(`/api/whatsapp-group-bindings/${bindingId}`, {
      method: 'DELETE',
      headers: {
        Origin: window.location.origin,
        'X-CSRF-Token': csrfToken,
      },
    }),
}
