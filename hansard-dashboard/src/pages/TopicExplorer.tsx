import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useSupabaseRpc } from '@/hooks/useSupabaseRpc'
import { supabase } from '@/lib/supabase'
import type { TopicResult, TopicDetail } from '@/lib/types'
import { formatNumber, formatDate, sectionTypeLabel, hansardUrl } from '@/lib/utils'

const SECTION_TYPES = ['OS', 'OA', 'WA', 'WANA', 'BP', 'BI', 'WS']
const PARLIAMENTS = [12, 13, 14, 15]

function useDebounce(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

export function TopicExplorer() {
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialise filter state from the URL so filtered views are shareable.
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '')
  const [dateFrom, setDateFrom] = useState(() => searchParams.get('from') ?? '')
  const [dateTo, setDateTo] = useState(() => searchParams.get('to') ?? '')
  const [selectedSections, setSelectedSections] = useState<string[]>(() => {
    const raw = searchParams.get('types')
    return raw ? raw.split(',').filter(Boolean) : []
  })
  const [selectedParliament, setSelectedParliament] = useState<number | null>(() => {
    const raw = searchParams.get('parl')
    return raw ? Number(raw) : null
  })
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const [expandedDetail, setExpandedDetail] = useState<TopicDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const debouncedSearch = useDebounce(search, 300)

  // Keep the URL in sync with the filters (replace, not push, so typing doesn't
  // spam the history stack).
  useEffect(() => {
    const next = new URLSearchParams()
    if (search) next.set('q', search)
    if (dateFrom) next.set('from', dateFrom)
    if (dateTo) next.set('to', dateTo)
    if (selectedSections.length > 0) next.set('types', selectedSections.join(','))
    if (selectedParliament !== null) next.set('parl', String(selectedParliament))
    setSearchParams(next, { replace: true })
  }, [search, dateFrom, dateTo, selectedSections, selectedParliament, setSearchParams])

  const rpcParams: Record<string, unknown> = {
    p_query: debouncedSearch || null,
    p_date_from: dateFrom || null,
    p_date_to: dateTo || null,
    p_section_types: selectedSections.length > 0 ? selectedSections : null,
    p_parliament_no: selectedParliament,
    p_limit: 100,
  }

  const deps = [debouncedSearch, dateFrom, dateTo, selectedSections.join(','), selectedParliament]

  const { data: topics, loading, error, refetch } =
    useSupabaseRpc<TopicResult[]>('search_topics', rpcParams, deps)

  async function loadDetail(title: string, date: string) {
    const key = `${title}::${date}`
    if (expandedRow === key) {
      setExpandedRow(null)
      setExpandedDetail(null)
      return
    }
    setExpandedRow(key)
    setExpandedDetail(null)
    setDetailLoading(true)
    const { data } = await supabase.rpc('topic_detail', {
      p_discussion_title: title,
      p_sitting_date: date,
    })
    setDetailLoading(false)
    if (data) setExpandedDetail(data as TopicDetail)
  }

  function toggleSection(code: string) {
    setSelectedSections(prev =>
      prev.includes(code) ? prev.filter(s => s !== code) : [...prev, code]
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-navy mb-1">Topic Explorer</h1>
        <p className="text-gray-600 text-sm">
          Search and filter parliamentary debates by topic, date, and section type.
        </p>
      </div>

      {/* Filters */}
      <Card>
        <div className="p-4 space-y-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <Input
              placeholder="Search topics, speakers, or speech content..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>

          <div className="flex flex-wrap gap-4">
            {/* Date range */}
            <div className="flex items-center gap-2 text-sm">
              <label className="text-gray-600 whitespace-nowrap">From</label>
              <Input
                type="date"
                value={dateFrom}
                onChange={e => setDateFrom(e.target.value)}
                className="w-40"
              />
              <label className="text-gray-600 whitespace-nowrap">To</label>
              <Input
                type="date"
                value={dateTo}
                onChange={e => setDateTo(e.target.value)}
                className="w-40"
              />
            </div>

            {/* Parliament */}
            <div className="flex items-center gap-2 text-sm">
              <label className="text-gray-600">Parliament</label>
              <div className="flex gap-1">
                <button
                  onClick={() => setSelectedParliament(null)}
                  className={`px-2 py-1 rounded text-xs border ${selectedParliament === null ? 'bg-teal text-white border-teal' : 'border-gray-200 hover:border-gray-400'}`}
                >
                  All
                </button>
                {PARLIAMENTS.map(p => (
                  <button
                    key={p}
                    onClick={() => setSelectedParliament(selectedParliament === p ? null : p)}
                    className={`px-2 py-1 rounded text-xs border ${selectedParliament === p ? 'bg-teal text-white border-teal' : 'border-gray-200 hover:border-gray-400'}`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Section types */}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-gray-600">Type</span>
            {SECTION_TYPES.map(code => (
              <button
                key={code}
                onClick={() => toggleSection(code)}
                className={`px-2 py-1 rounded text-xs border transition-colors ${selectedSections.includes(code) ? 'bg-teal text-white border-teal' : 'border-gray-200 hover:border-gray-400'}`}
              >
                {sectionTypeLabel(code)}
              </button>
            ))}
            {selectedSections.length > 0 && (
              <button
                onClick={() => setSelectedSections([])}
                className="text-xs text-gray-400 hover:text-gray-600 underline"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </Card>

      {/* Results */}
      {error ? (
        <div className="text-center p-6 bg-red-50 rounded-lg">
          <p className="text-red-600 mb-2">Failed to load topics: {error}</p>
          <button onClick={refetch} className="text-teal hover:underline text-sm">Retry</button>
        </div>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50">
                  <th className="p-4 text-left font-medium text-gray-600 w-8"></th>
                  <th className="p-4 text-left font-medium text-gray-600">Discussion Title</th>
                  <th className="p-4 text-left font-medium text-gray-600">Date</th>
                  <th className="p-4 text-left font-medium text-gray-600">Type</th>
                  <th className="p-4 text-right font-medium text-gray-600">Speakers</th>
                  <th className="p-4 text-right font-medium text-gray-600">Words</th>
                  <th className="p-4 text-center font-medium text-gray-600">Parl</th>
                </tr>
              </thead>
              <tbody>
                {loading
                  ? Array.from({ length: 8 }).map((_, i) => (
                      <tr key={i} className="border-b">
                        {Array.from({ length: 7 }).map((_, j) => (
                          <td key={j} className="p-4">
                            <div className="h-4 bg-gray-200 animate-pulse rounded" style={{ width: j === 1 ? '80%' : '60%' }} />
                          </td>
                        ))}
                      </tr>
                    ))
                  : (topics ?? []).map(topic => {
                      const rowKey = `${topic.discussion_title}::${topic.sitting_date}`
                      const isExpanded = expandedRow === rowKey
                      return (
                        <>
                          <tr
                            key={rowKey}
                            onClick={() => loadDetail(topic.discussion_title, topic.sitting_date)}
                            className="border-b hover:bg-gray-50 cursor-pointer transition-colors"
                          >
                            <td className="p-4 text-gray-400">
                              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </td>
                            <td className="p-4 font-medium text-navy max-w-xs">
                              <span className="line-clamp-2">{topic.discussion_title}</span>
                            </td>
                            <td className="p-4 text-gray-600 whitespace-nowrap">{formatDate(topic.sitting_date)}</td>
                            <td className="p-4">
                              <Badge variant="secondary">{sectionTypeLabel(topic.section_type)}</Badge>
                            </td>
                            <td className="p-4 text-right tabular-nums">{formatNumber(topic.speaker_count)}</td>
                            <td className="p-4 text-right tabular-nums">{formatNumber(topic.total_words)}</td>
                            <td className="p-4 text-center text-gray-500">{topic.parliament_no}</td>
                          </tr>
                          {isExpanded && (
                            <tr key={`${rowKey}-detail`} className="bg-gray-50 border-b">
                              <td colSpan={7} className="p-4">
                                {detailLoading ? (
                                  <div className="space-y-2">
                                    {Array.from({ length: 3 }).map((_, i) => (
                                      <div key={i} className="h-12 bg-gray-200 animate-pulse rounded" />
                                    ))}
                                  </div>
                                ) : expandedDetail ? (
                                  <div className="space-y-3">
                                    <div className="flex items-center justify-between">
                                      <p className="font-semibold text-navy">{expandedDetail.discussion_title}</p>
                                      <a
                                        href={hansardUrl(expandedDetail.sitting_date)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-flex items-center gap-1 text-xs text-teal hover:underline"
                                        onClick={e => e.stopPropagation()}
                                      >
                                        <ExternalLink size={12} /> Official Hansard
                                      </a>
                                    </div>
                                    <div className="space-y-2">
                                      {(expandedDetail.speakers ?? []).filter(s => !s.is_chair).map((speaker, i) => (
                                        <div key={i} className="bg-white rounded border p-3 space-y-1">
                                          <div className="flex items-center justify-between gap-2">
                                            <span className="font-medium text-sm">{speaker.mp_name}</span>
                                            <div className="flex items-center gap-2">
                                              <Badge variant="outline">{sectionTypeLabel(speaker.section_type)}</Badge>
                                              <span className="text-xs text-gray-400">{formatNumber(speaker.word_count)} words</span>
                                            </div>
                                          </div>
                                          {speaker.one_liner ? (
                                            <div className="flex items-start gap-2">
                                              <p className="text-xs text-gray-600 italic">{speaker.one_liner}</p>
                                              <Badge variant="ai" className="shrink-0 text-xs">AI</Badge>
                                            </div>
                                          ) : speaker.speech_details ? (
                                            <p className="text-xs text-gray-600 mt-1 line-clamp-3">
                                              {speaker.speech_details.length > 300
                                                ? speaker.speech_details.slice(0, 300) + '…'
                                                : speaker.speech_details}
                                            </p>
                                          ) : null}
                                          {speaker.themes && speaker.themes.length > 0 && (
                                            <div className="flex flex-wrap gap-1 pt-1">
                                              {speaker.themes.map((theme, ti) => (
                                                <span key={ti} className="text-xs bg-gray-100 text-gray-600 rounded px-2 py-0.5">
                                                  {theme}
                                                </span>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                ) : (
                                  <p className="text-sm text-gray-500">No detail available.</p>
                                )}
                              </td>
                            </tr>
                          )}
                        </>
                      )
                    })}
              </tbody>
            </table>
          </div>
          {!loading && (
            <div className="px-4 py-3 border-t text-sm text-gray-500 bg-gray-50">
              {(topics ?? []).length} result{(topics ?? []).length !== 1 ? 's' : ''}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
