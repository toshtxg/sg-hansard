import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useSupabaseRpc } from '@/hooks/useSupabaseRpc'
import { supabase } from '@/lib/supabase'
import type { MPSummary, MPActivityPoint, MPTopic, MPSectionBreakdown, MPDiscussion, TopicDetail, MPAttendance } from '@/lib/types'
import { formatNumber, formatDate, sectionTypeLabel, hansardUrl, cn } from '@/lib/utils'

const CHART_COLORS = ['#0d9488', '#3b82f6', '#8b5cf6', '#f59e0b', '#ef4444', '#10b981', '#6366f1']

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Card>
      <CardContent className="pt-6 text-center">
        <p className="text-red-600 mb-2">{message}</p>
        <button onClick={onRetry} className="text-teal hover:underline text-sm">Retry</button>
      </CardContent>
    </Card>
  )
}

export function MPDetail() {
  const { name } = useParams<{ name: string }>()
  const mpName = name ? decodeURIComponent(name) : ''

  const [activityMetric, setActivityMetric] = useState<'word_count' | 'speech_count'>('word_count')
  const [activityGranularity, setActivityGranularity] = useState<'year' | 'quarter'>('year')
  const [discussionPage, setDiscussionPage] = useState(1)
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, TopicDetail>>({})
  const [detailLoading, setDetailLoading] = useState(false)

  const deps = [mpName]

  const { data: summary, loading: summaryLoading, error: summaryError, refetch: refetchSummary } =
    useSupabaseRpc<MPSummary>('mp_summary', { p_mp_name: mpName }, deps)

  // Attendance card. If the RPC isn't applied in Supabase yet it will error —
  // in that case we hide the card entirely (no error box).
  const { data: attendance, error: attendanceError } =
    useSupabaseRpc<MPAttendance>('mp_attendance', { p_mp_name: mpName }, deps)

  const { data: activity, loading: activityLoading, error: activityError, refetch: refetchActivity } =
    useSupabaseRpc<MPActivityPoint[]>(
      'mp_activity_over_time',
      { p_mp_name: mpName, p_granularity: activityGranularity },
      [mpName, activityGranularity]
    )

  const { data: topics, loading: topicsLoading, error: topicsError, refetch: refetchTopics } =
    useSupabaseRpc<MPTopic[]>('mp_top_topics', { p_mp_name: mpName, p_limit: 15 }, deps)

  const { data: sections, loading: sectionsLoading, error: sectionsError, refetch: refetchSections } =
    useSupabaseRpc<MPSectionBreakdown[]>('mp_section_breakdown', { p_mp_name: mpName }, deps)

  const { data: discussions, loading: discussionsLoading, error: discussionsError, refetch: refetchDiscussions } =
    useSupabaseRpc<MPDiscussion[]>('mp_recent_discussions', { p_mp_name: mpName, p_limit: 60 }, deps)

  const DISCUSSION_PAGE_SIZE = 15
  const visibleDiscussions = (discussions ?? []).slice(0, discussionPage * DISCUSSION_PAGE_SIZE)
  const hasMoreDiscussions = (discussions ?? []).length > visibleDiscussions.length

  async function toggleDiscussion(title: string, date: string) {
    const key = `${title}::${date}`
    if (expandedKey === key) {
      setExpandedKey(null)
      return
    }
    setExpandedKey(key)
    if (detailCache[key]) return
    setDetailLoading(true)
    const { data } = await supabase.rpc('topic_detail', {
      p_discussion_title: title,
      p_sitting_date: date,
    })
    setDetailLoading(false)
    if (data) setDetailCache(prev => ({ ...prev, [key]: data as TopicDetail }))
  }

  function roleLabel(sectionType: string): string {
    const map: Record<string, string> = {
      OS: 'Spoke', OA: 'Oral Q&A', WA: 'Written Q&A',
      WANA: 'Written Q&A', BP: 'Debated', BI: 'Introduced', WS: 'Statement',
    }
    return map[sectionType] ?? sectionType
  }

  if (!mpName) {
    return <div className="text-center p-12 text-gray-500">No MP specified.</div>
  }

  return (
    <div className="space-y-8">
      {/* Back + Title */}
      <div>
        <Link to="/mp" className="inline-flex items-center gap-1 text-sm text-teal hover:underline mb-4">
          <ArrowLeft size={14} /> Back to MPs
        </Link>
        <h1 className="text-3xl font-bold text-navy">{mpName}</h1>
      </div>

      {/* Section A: Summary stats */}
      {summaryLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-6">
                <div className="h-8 bg-gray-200 animate-pulse rounded w-1/2 mb-2" />
                <div className="h-4 bg-gray-200 animate-pulse rounded w-3/4" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : summaryError ? (
        <ErrorCard message={`Failed to load summary: ${summaryError}`} onRetry={refetchSummary} />
      ) : summary ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Total Words</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">{formatNumber(summary.total_words)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Total Speeches</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">{formatNumber(summary.total_speeches)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Sittings Active</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">{formatNumber(summary.sittings_active)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Parliaments</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">
                {summary.parliaments?.length ? summary.parliaments.join(', ') : '—'}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {formatDate(summary.first_sitting)} — {formatDate(summary.last_sitting)}
              </p>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {/* Section A2: Attendance (hidden when the RPC isn't available yet) */}
      {!attendanceError && attendance && attendance.sittings_total > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Attendance Rate</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">
                {attendance.attendance_rate != null ? `${Math.round(attendance.attendance_rate * 100)}%` : '—'}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Sittings Present</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">{formatNumber(attendance.sittings_present)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Sittings Recorded</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">{formatNumber(attendance.sittings_total)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Approved Leave (PTBA)</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-navy">{formatNumber(attendance.ptba_count)}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Section B: Activity Over Time */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>Activity Over Time</CardTitle>
            <div className="flex flex-wrap gap-2">
              <div className="flex rounded-md border overflow-hidden">
                <button
                  onClick={() => setActivityMetric('word_count')}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${activityMetric === 'word_count' ? 'bg-teal text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                >
                  Words
                </button>
                <button
                  onClick={() => setActivityMetric('speech_count')}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${activityMetric === 'speech_count' ? 'bg-teal text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                >
                  Speeches
                </button>
              </div>
              <div className="flex rounded-md border overflow-hidden">
                <button
                  onClick={() => setActivityGranularity('year')}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${activityGranularity === 'year' ? 'bg-teal text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                >
                  Year
                </button>
                <button
                  onClick={() => setActivityGranularity('quarter')}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${activityGranularity === 'quarter' ? 'bg-teal text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                >
                  Quarter
                </button>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {activityLoading ? (
            <div className="h-64 bg-gray-100 animate-pulse rounded" />
          ) : activityError ? (
            <ErrorCard message={`Failed to load activity: ${activityError}`} onRetry={refetchActivity} />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={activity ?? []} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} width={60} />
                <Tooltip
                  formatter={(v) => formatNumber(v as number)}
                  labelStyle={{ fontWeight: 600 }}
                />
                <Line
                  type="monotone"
                  dataKey={activityMetric}
                  stroke="#0d9488"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  name={activityMetric === 'word_count' ? 'Words' : 'Speeches'}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Section C & D: Topics + Section Breakdown */}
      <div className="space-y-6">
        {/* Top Topics */}
        <Card>
          <CardHeader>
            <CardTitle>Top Topics</CardTitle>
          </CardHeader>
          <CardContent>
            {topicsLoading ? (
              <div className="h-64 bg-gray-100 animate-pulse rounded" />
            ) : topicsError ? (
              <ErrorCard message={`Failed to load topics: ${topicsError}`} onRetry={refetchTopics} />
            ) : (
              <ResponsiveContainer width="100%" height={400}>
                <BarChart
                  data={(topics ?? []).slice(0, 15)}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 8, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={v => formatNumber(v as number)} />
                  <YAxis
                    type="category"
                    dataKey="discussion_title"
                    width={280}
                    tick={{ fontSize: 13 }}
                    tickFormatter={v => v.length > 42 ? v.slice(0, 42) + '…' : v}
                  />
                  <Tooltip
                    formatter={(v) => formatNumber(v as number)}
                    labelStyle={{ fontWeight: 600, fontSize: 13 }}
                  />
                  <Bar dataKey="word_count" fill="#0d9488" name="Words" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* Section Type Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle>Speech Type Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            {sectionsLoading ? (
              <div className="h-64 bg-gray-100 animate-pulse rounded" />
            ) : sectionsError ? (
              <ErrorCard message={`Failed to load sections: ${sectionsError}`} onRetry={refetchSections} />
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={(sections ?? []).map(s => ({ ...s, name: sectionTypeLabel(s.section_type) }))}
                    dataKey="word_count"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={2}
                  >
                    {(sections ?? []).map((_, index) => (
                      <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => formatNumber(v as number)} />
                  <Legend
                    formatter={value => <span className="text-xs">{value}</span>}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Section E: Recent Discussions */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Discussions</CardTitle>
          <p className="text-sm text-gray-500">Parliamentary discussions this MP participated in. Expand any row to see the full exchange.</p>
        </CardHeader>
        <CardContent className="p-0">
          {discussionsLoading ? (
            <div className="space-y-px">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-14 bg-gray-100 animate-pulse m-4 rounded" />
              ))}
            </div>
          ) : discussionsError ? (
            <div className="p-6">
              <ErrorCard message={`Failed to load discussions: ${discussionsError}`} onRetry={refetchDiscussions} />
            </div>
          ) : (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-gray-50 text-left">
                    <th className="px-4 py-3 font-medium text-gray-500 w-8"></th>
                    <th className="px-4 py-3 font-medium text-gray-500 whitespace-nowrap">Date</th>
                    <th className="px-4 py-3 font-medium text-gray-500">Discussion</th>
                    <th className="px-4 py-3 font-medium text-gray-500 whitespace-nowrap hidden sm:table-cell">Role</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-right whitespace-nowrap hidden sm:table-cell">Words</th>
                    <th className="px-4 py-3 font-medium text-gray-500 text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {visibleDiscussions.map((d) => {
                    const key = `${d.discussion_title}::${d.sitting_date}`
                    const isExpanded = expandedKey === key
                    const detail = detailCache[key]
                    return (
                      <>
                        <tr
                          key={key}
                          onClick={() => toggleDiscussion(d.discussion_title, d.sitting_date)}
                          className="border-b hover:bg-gray-50 cursor-pointer transition-colors"
                        >
                          <td className="px-4 py-3 text-gray-400 text-xs">
                            {isExpanded ? '▼' : '▶'}
                          </td>
                          <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                            {formatDate(d.sitting_date)}
                          </td>
                          <td className="px-4 py-3 font-medium text-navy">
                            <span className="line-clamp-2">{d.discussion_title}</span>
                          </td>
                          <td className="px-4 py-3 hidden sm:table-cell">
                            <Badge variant="secondary">{roleLabel(d.primary_section_type)}</Badge>
                          </td>
                          <td className="px-4 py-3 text-right tabular-nums text-gray-600 hidden sm:table-cell">
                            {formatNumber(d.mp_words)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <a
                              href={hansardUrl(d.sitting_date)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs text-teal hover:underline"
                              onClick={e => e.stopPropagation()}
                            >
                              <ExternalLink size={12} /> Hansard
                            </a>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr key={`${key}-detail`} className="bg-slate-50 border-b">
                            <td colSpan={6} className="px-6 py-4">
                              {detailLoading && !detail ? (
                                <div className="space-y-2">
                                  {Array.from({ length: 3 }).map((_, i) => (
                                    <div key={i} className="h-10 bg-gray-200 animate-pulse rounded" />
                                  ))}
                                </div>
                              ) : detail ? (
                                <div className="space-y-2">
                                  <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">Full exchange</p>
                                  {(detail.speakers ?? []).filter(s => !s.is_chair).map((speaker, i) => (
                                    <div
                                      key={i}
                                      className={cn(
                                        'flex items-start gap-3 rounded-lg px-3 py-2 text-sm',
                                        speaker.mp_name === mpName
                                          ? 'bg-teal/10 border border-teal/20'
                                          : 'bg-white border border-gray-100'
                                      )}
                                    >
                                      <div className="flex-1 min-w-0">
                                        <div className="flex flex-wrap items-center gap-2">
                                          <span className={cn('font-medium', speaker.mp_name === mpName ? 'text-teal' : 'text-navy')}>
                                            {speaker.mp_name ?? 'Unknown'}
                                          </span>
                                          <Badge variant="outline" className="text-xs">{sectionTypeLabel(speaker.section_type)}</Badge>
                                          <span className="text-xs text-gray-400">{formatNumber(speaker.word_count)} words</span>
                                        </div>
                                        {speaker.one_liner ? (
                                          <div className="flex items-start gap-2 mt-1">
                                            <p className="text-xs text-gray-500 italic">{speaker.one_liner}</p>
                                            <Badge variant="ai" className="shrink-0 text-xs">AI</Badge>
                                          </div>
                                        ) : speaker.speech_details ? (
                                          <p className="text-xs text-gray-500 mt-1 line-clamp-3">
                                            {speaker.speech_details.length > 300
                                              ? speaker.speech_details.slice(0, 300) + '…'
                                              : speaker.speech_details}
                                          </p>
                                        ) : null}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
              {hasMoreDiscussions && (
                <div className="p-4 text-center border-t">
                  <Button variant="outline" onClick={() => setDiscussionPage(p => p + 1)}>
                    Load More
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
