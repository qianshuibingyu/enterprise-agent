import { ref } from 'vue'

/**
 * Lightweight hash-based navigation.
 *
 * The whole application used to live behind in-memory refs: switching a tab,
 * opening an inquiry, opening operation logs or closing anything just flipped a
 * boolean, so the browser Back button did nothing and a refresh always dropped
 * the operator on the first page. This module keeps the view state in the URL
 * fragment so every screen is addressable and history works.
 *
 * Hash (not pathname) is deliberate: the deployed nginx already proxies /api,
 * /auth and /health, and an outer HTTPS reverse proxy owns the real path.
 * Nothing outside this repository has to change for deep links to work.
 */

export type WorkspaceView = 'messages' | 'review' | 'customers' | 'customerMessages'
export type RoutePage = WorkspaceView | 'inquiry' | 'message' | 'logs' | 'settings' | 'groupBinding'

export type AppRoute = {
  page: RoutePage
  /** Inquiry id / message id for detail pages. */
  id: number | null
  /** The list view a detail page came from, and the view restored on Back. */
  view: WorkspaceView
  mpage: number
  ipage: number
  mh: string
  mi: string
  ma: string
  mc: string
  ih: string
  box: '' | 'processed' | 'ignored'
  logsInquiry: number | null
  /** WhatsApp group JID for the operator-managed group binding page. */
  groupJid: string | null
}

const VIEWS: WorkspaceView[] = ['messages', 'review', 'customers', 'customerMessages']

const PAGE_PATH: Record<RoutePage, string> = {
  messages: '/messages',
  review: '/review',
  customers: '/customers',
  customerMessages: '/customer-messages',
  inquiry: '/inquiries',
  message: '/message',
  logs: '/logs',
  settings: '/settings',
  groupBinding: '/group-binding',
}

const PATH_PAGE: Record<string, RoutePage> = {
  '/messages': 'messages',
  '/review': 'review',
  '/customers': 'customers',
  '/customer-messages': 'customerMessages',
  '/inquiries': 'inquiry',
  '/message': 'message',
  '/logs': 'logs',
  '/settings': 'settings',
  '/group-binding': 'groupBinding',
}

export function defaultRoute(): AppRoute {
  return {
    page: 'messages',
    id: null,
    view: 'messages',
    mpage: 1,
    ipage: 1,
    mh: 'pending',
    mi: '',
    ma: 'all',
    mc: '',
    ih: '',
    box: '',
    logsInquiry: null,
    groupJid: null,
  }
}

function isView(value: string | null): value is WorkspaceView {
  return value !== null && VIEWS.includes(value as WorkspaceView)
}

function positiveInt(value: string | null, fallback: number): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

export function parseHash(hash: string): AppRoute {
  const base = defaultRoute()
  const raw = hash.replace(/^#/, '')
  if (!raw.startsWith('/')) return base
  const questionMark = raw.indexOf('?')
  const pathPart = questionMark < 0 ? raw : raw.slice(0, questionMark)
  const query = new URLSearchParams(questionMark < 0 ? '' : raw.slice(questionMark + 1))
  const segments = pathPart.split('/').filter(Boolean)
  const page = PATH_PAGE[`/${segments[0] ?? ''}`] ?? 'messages'
  const id = segments[1] && /^\d+$/.test(segments[1]) ? Number(segments[1]) : null
  const box = query.get('box')
  const logsInquiry = query.get('log')
  const rawGroupJid = query.get('gjid')
  const groupJid = page === 'groupBinding' && rawGroupJid && rawGroupJid.length <= 255 ? rawGroupJid : null
  const parsedView = isView(query.get('view')) ? (query.get('view') as WorkspaceView) : base.view
  const view = ['messages', 'review', 'customers', 'customerMessages'].includes(page) ? page as WorkspaceView : parsedView
  return {
    page,
    id,
    view,
    mpage: positiveInt(query.get('mpage'), base.mpage),
    ipage: positiveInt(query.get('ipage'), base.ipage),
    mh: query.get('mh') ?? base.mh,
    mi: query.get('mi') ?? base.mi,
    ma: query.get('ma') ?? base.ma,
    mc: query.get('mc') ?? base.mc,
    ih: query.get('ih') ?? base.ih,
    box: box === 'processed' || box === 'ignored' ? box : '',
    logsInquiry: logsInquiry && /^\d+$/.test(logsInquiry) ? Number(logsInquiry) : null,
    groupJid,
  }
}

export function serializeRoute(r: AppRoute): string {
  const base = defaultRoute()
  let path = PAGE_PATH[r.page]
  if ((r.page === 'inquiry' || r.page === 'message') && r.id !== null) path += `/${r.id}`
  const q = new URLSearchParams()
  if (r.view !== base.view) q.set('view', r.view)
  if (r.mpage !== base.mpage) q.set('mpage', String(r.mpage))
  if (r.ipage !== base.ipage) q.set('ipage', String(r.ipage))
  if (r.mh !== base.mh) q.set('mh', r.mh)
  if (r.mi !== base.mi) q.set('mi', r.mi)
  if (r.ma !== base.ma) q.set('ma', r.ma)
  if (r.mc !== base.mc) q.set('mc', r.mc)
  if (r.ih !== base.ih) q.set('ih', r.ih)
  if (r.box) q.set('box', r.box)
  if (r.logsInquiry !== null) q.set('log', String(r.logsInquiry))
  if (r.page === 'groupBinding' && r.groupJid) q.set('gjid', r.groupJid)
  const search = q.toString()
  return `#${path}${search ? `?${search}` : ''}`
}

export const route = ref<AppRoute>(defaultRoute())

export type RouteChange = { initial: boolean; viaHistory: boolean }
type ChangeHandler = (next: AppRoute, info: RouteChange) => void
let handler: ChangeHandler | null = null

function appDepth(): number {
  const state = window.history.state as { appDepth?: number } | null
  return typeof state?.appDepth === 'number' ? state.appDepth : 0
}

export function initRouter(onChange: ChangeHandler): void {
  handler = onChange
  window.addEventListener('popstate', () => {
    route.value = parseHash(window.location.hash)
    handler?.(route.value, { initial: false, viaHistory: true })
  })
  const initial = parseHash(window.location.hash)
  route.value = initial
  const url = serializeRoute(initial)
  if (window.location.hash !== url || appDepth() === 0) {
    window.history.replaceState({ appDepth: 0 }, '', url)
  }
  handler?.(initial, { initial: true, viaHistory: false })
}

/** Push (or replace) a new page. Filters and paging should use replace=true. */
export function navigate(partial: Partial<AppRoute>, replace = false): void {
  const next: AppRoute = { ...route.value, ...partial }
  const url = serializeRoute(next)
  if (window.location.hash === url && route.value.page === next.page) {
    route.value = next
    return
  }
  if (replace) window.history.replaceState({ appDepth: appDepth() }, '', url)
  else window.history.pushState({ appDepth: appDepth() + 1 }, '', url)
  route.value = next
  handler?.(next, { initial: false, viaHistory: false })
}

/** Browser Back when we own history, otherwise fall back to a known parent page. */
export function goBack(fallback: Partial<AppRoute> = {}): void {
  if (appDepth() > 0) {
    window.history.back()
    return
  }
  navigate({ page: 'messages', id: null, logsInquiry: null, ...fallback }, true)
}

export function isStandalonePage(page: RoutePage): boolean {
  return page === 'inquiry' || page === 'message' || page === 'logs' || page === 'settings' || page === 'groupBinding'
}
