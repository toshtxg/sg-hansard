import { useMemo, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, ExternalLink, ChevronDown, ChevronRight, Users } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useSupabaseRpc } from '@/hooks/useSupabaseRpc'
import type { SittingDetail as SittingDetailData, SittingSpeech } from '@/lib/types'
import { formatNumber, formatDate, sectionTypeLabel, hansardUrl } from '@/lib/utils'

interface SpeechGroup {
  title: string
  sectionType: string
  speeches: SittingSpeech[]
}

/** Group speeches by discussion_title, preserving sitting order (row_num). */
function groupSpeeches(speeches: SittingSpeech[]): SpeechGroup[] {
  const groups: SpeechGroup[] = []
  let current: SpeechGroup | null = null
  for (const sp of speeches) {
    const title = sp.discussion_title ?? 'Untitled'
    if (!current || current.title !== title) {
      current = { title, sectionType: sp.section_type, speeches: [] }
      groups.push(current)
    }
    current.speeches.push(sp)
  }
  return groups
}

/** True when the error looks like "the RPC isn't deployed yet" rather than a real failure. */
function isMissingRpcError(message: string): boolean {
  return /could not find the function|does not exist|schema cache/i.test(message)
}

export function SittingDetail() {
  const { date } = useParams<{ date: string }>()
  const sittingDate = date ?? ''
  const [absentOpen, setAbsentOpen] = useState(false)

  const { data: detail, loading, error, refetch } = useSupabaseRpc<SittingDetailData>(
    'sitting_detail',
    { p_sitting_date: sittingDate },
    [sittingDate]
  )

  const speechGroups = useMemo(() => groupSpeeches(detail?.speeches ?? []), [detail])

  if (!sittingDate) {
    return <div className="text-center p-12 text-gray-500">No sitting specified.</div>
  }

  return (
    <div className="space-y-8">
      {/* Back + Title */}
      <div>
        <Link to="/" className="inline-flex items-center gap-1 text-sm text-teal hover:underline mb-4">
          <ArrowLeft size={14} /> Back to Overview
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold text-navy">Sitting of {formatDate(sittingDate)}</h1>
          <a
            href={detail?.source_url ?? hansardUrl(sittingDate)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm text-teal hover:underline"
          >
            <ExternalLink size={14} /> Official Hansard
          </a>
        </div>
      </div>

      {loading ? (
        <div className="space-y-6">
          <Card>
            <CardContent className="pt-6 space-y-2">
              <div className="h-4 bg-gray-200 animate-pulse rounded w-full" />
              <div className="h-4 bg-gray-200 animate-pulse rounded w-5/6" />
              <div className="h-4 bg-gray-200 animate-pulse rounded w-2/3" />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 space-y-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 bg-gray-200 animate-pulse rounded" />
              ))}
            </CardContent>
          </Card>
        </div>
      ) : error ? (
        isMissingRpcError(error) ? (
          // The sitting_detail RPC hasn't been applied in Supabase yet — fail soft.
          <Card>
            <CardContent className="pt-6 text-center text-gray-500 space-y-2">
              <p>Sitting detail is not available yet.</p>
              <p className="text-sm">
                You can still read this sitting on the{' '}
                <a
                  href={hansardUrl(sittingDate)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-teal hover:underline"
                >
                  official Hansard
                </a>
                .
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="text-center p-6 bg-red-50 rounded-lg">
            <p className="text-red-600">Failed to load sitting detail: {error}</p>
            <button onClick={refetch} className="mt-2 text-teal hover:underline text-sm">Retry</button>
          </div>
        )
      ) : detail ? (
        <>
          {/* AI 3-sentence summary */}
          {detail.summary_3_sentences && (
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base">Sitting Summary</CardTitle>
                  <Badge variant="ai" className="text-xs">AI</Badge>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-gray-700 leading-relaxed">{detail.summary_3_sentences}</p>
              </CardContent>
            </Card>
          )}

          {/* Attendance strip */}
          {detail.attendance && detail.attendance.total > 0 && (
            <Card>
              <CardContent className="pt-6">
                <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
                  <span className="inline-flex items-center gap-2 font-medium text-navy">
                    <Users size={16} className="text-teal" />
                    {formatNumber(detail.attendance.present_count)} of {formatNumber(detail.attendance.total)} MPs present
                  </span>
                  {detail.attendance.ptba.length > 0 && (
                    <span className="text-gray-600">
                      {formatNumber(detail.attendance.ptba.length)} on approved leave (PTBA)
                    </span>
                  )}
                  {detail.attendance.absent.length > 0 && (
                    <button
                      onClick={() => setAbsentOpen(o => !o)}
                      className="inline-flex items-center gap-1 text-teal hover:underline"
                    >
                      {absentOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      {formatNumber(detail.attendance.absent.length)} absent
                    </button>
                  )}
                </div>
                {absentOpen && detail.attendance.absent.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {detail.attendance.absent.map(name => {
                      const onLeave = detail.attendance!.ptba.some(p => p.mp_name_cleaned === name)
                      return (
                        <span
                          key={name}
                          className="text-xs bg-gray-100 text-gray-600 rounded px-2 py-0.5"
                          title={onLeave ? 'On approved leave (PTBA)' : undefined}
                        >
                          {name}
                          {onLeave && ' · PTBA'}
                        </span>
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Speeches grouped by discussion */}
          <section>
            <h2 className="text-2xl font-bold text-navy mb-4">Proceedings</h2>
            {speechGroups.length === 0 ? (
              <Card>
                <CardContent className="pt-6 text-center text-gray-500">
                  No speeches recorded for this sitting.
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-4">
                {speechGroups.map((group, gi) => (
                  <Card key={`${group.title}-${gi}`}>
                    <CardHeader className="pb-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <CardTitle className="text-base text-navy">{group.title}</CardTitle>
                        <Badge variant="secondary" className="shrink-0">
                          {sectionTypeLabel(group.sectionType)}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <div className="divide-y">
                        {group.speeches.map(sp => (
                          <div key={sp.row_num} className="py-2 flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-3">
                            <div className="sm:w-56 shrink-0">
                              {sp.mp_name ? (
                                <Link
                                  to={`/mp/${encodeURIComponent(sp.mp_name)}`}
                                  className="text-sm font-medium text-navy hover:text-teal hover:underline"
                                >
                                  {sp.mp_name}
                                </Link>
                              ) : (
                                <span className="text-sm text-gray-400">—</span>
                              )}
                            </div>
                            {sp.one_liner ? (
                              <div className="flex items-start gap-2 min-w-0">
                                <p className="text-xs text-gray-600 italic">{sp.one_liner}</p>
                                <Badge variant="ai" className="shrink-0 text-xs">AI</Badge>
                              </div>
                            ) : (
                              <p className="text-xs text-gray-400">
                                {sp.word_count != null ? `${formatNumber(sp.word_count)} words` : '—'}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </section>
        </>
      ) : (
        <Card>
          <CardContent className="pt-6 text-center text-gray-500">
            No data found for this sitting.
          </CardContent>
        </Card>
      )}
    </div>
  )
}
