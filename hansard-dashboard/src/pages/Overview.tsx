import { Link } from 'react-router-dom'
import { Users, BookOpen, Calendar, FileText, TrendingUp, ArrowRight, ExternalLink } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useSupabaseRpc } from '@/hooks/useSupabaseRpc'
import type { OverviewStats, RecentSitting } from '@/lib/types'
import { formatNumber, formatDate, hansardUrl } from '@/lib/utils'

function StatCard({
  icon: Icon,
  label,
  value,
  loading,
}: {
  icon: React.ElementType
  label: string
  value: string
  loading: boolean
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
        <Icon className="h-4 w-4 text-teal" />
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-8 w-24 bg-gray-200 animate-pulse rounded" />
        ) : (
          <p className="text-3xl font-bold text-navy">{value}</p>
        )}
      </CardContent>
    </Card>
  )
}

export function Overview() {
  const { data: stats, loading: statsLoading, error: statsError, refetch: refetchStats } =
    useSupabaseRpc<OverviewStats>('overview_stats')

  const { data: recentRaw, loading: recentLoading, error: recentError, refetch: refetchRecent } =
    useSupabaseRpc<RecentSitting[]>('recent_sittings', { p_limit: 10 })

  return (
    <div className="space-y-12">
      {/* Hero */}
      <section className="text-center space-y-4 py-8">
        <h1 className="text-4xl sm:text-5xl font-bold text-navy">Singapore Hansard Explorer</h1>
        <p className="text-lg text-gray-600 max-w-2xl mx-auto">
          Explore speeches, debates, and parliamentary activity from the Singapore Parliament
          {stats?.earliest_sitting && (
            <> since <span className="font-medium text-navy">{new Date(stats.earliest_sitting).getFullYear()}</span></>
          )}
          . Data sourced from the official{' '}
          <a
            href="https://sprs.parl.gov.sg"
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal hover:underline"
          >
            Hansard records
          </a>
          .
        </p>
        {stats?.latest_sitting && (
          <p className="text-sm text-gray-500">
            Latest sitting: <span className="font-medium">{formatDate(stats.latest_sitting)}</span>
          </p>
        )}
      </section>

      {/* Stats */}
      <section>
        {statsError ? (
          <div className="text-center p-6 bg-red-50 rounded-lg">
            <p className="text-red-600">Failed to load statistics: {statsError}</p>
            <button onClick={refetchStats} className="mt-2 text-teal hover:underline text-sm">Retry</button>
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={FileText}
              label="Total Speeches"
              value={formatNumber(stats?.total_speeches)}
              loading={statsLoading}
            />
            <StatCard
              icon={Calendar}
              label="Total Sittings"
              value={formatNumber(stats?.total_sittings)}
              loading={statsLoading}
            />
            <StatCard
              icon={Users}
              label="Unique Speakers"
              value={formatNumber(stats?.total_speakers)}
              loading={statsLoading}
            />
            <StatCard
              icon={BookOpen}
              label="Total Words"
              value={formatNumber(stats?.total_words)}
              loading={statsLoading}
            />
          </div>
        )}
      </section>

      {/* Recent Sittings */}
      <section>
        <h2 className="text-2xl font-bold text-navy mb-4">Recent Sittings</h2>
        {recentError ? (
          <div className="text-center p-6 bg-red-50 rounded-lg">
            <p className="text-red-600">Failed to load recent sittings: {recentError}</p>
            <button onClick={refetchRecent} className="mt-2 text-teal hover:underline text-sm">Retry</button>
          </div>
        ) : (
          <Card>
            {/* Mobile: card list */}
            <div className="sm:hidden divide-y">
              {recentLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="flex items-center justify-between p-4">
                      <div className="space-y-2">
                        <div className="h-4 w-28 bg-gray-200 animate-pulse rounded" />
                        <div className="h-3 w-40 bg-gray-200 animate-pulse rounded" />
                      </div>
                      <div className="h-4 w-12 bg-gray-200 animate-pulse rounded" />
                    </div>
                  ))
                : (recentRaw ?? []).map((sitting) => (
                    <div key={sitting.sitting_date} className="flex items-center justify-between p-4">
                      <div className="min-w-0">
                        <Link to={`/sitting/${sitting.sitting_date}`} className="font-medium text-navy hover:text-teal hover:underline">
                          {formatDate(sitting.sitting_date)}
                        </Link>
                        <p className="text-xs text-gray-500 mt-0.5">
                          {formatNumber(sitting.speech_count)} speeches · {formatNumber(sitting.word_count)} words
                        </p>
                        {sitting.summary_3_sentences && (
                          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{sitting.summary_3_sentences}</p>
                        )}
                      </div>
                      <a
                        href={hansardUrl(sitting.sitting_date)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-2 text-teal hover:text-teal-700 shrink-0"
                        aria-label="View Hansard"
                      >
                        <ExternalLink size={18} />
                      </a>
                    </div>
                  ))}
            </div>

            {/* Desktop: table */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-gray-50">
                    <th className="text-left p-4 font-medium text-gray-600">Date</th>
                    <th className="text-right p-4 font-medium text-gray-600">Speeches</th>
                    <th className="text-right p-4 font-medium text-gray-600">Words</th>
                    <th className="p-4 font-medium text-gray-600">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {recentLoading
                    ? Array.from({ length: 5 }).map((_, i) => (
                        <tr key={i} className="border-b">
                          <td className="p-4"><div className="h-4 w-28 bg-gray-200 animate-pulse rounded" /></td>
                          <td className="p-4"><div className="h-4 w-16 bg-gray-200 animate-pulse rounded ml-auto" /></td>
                          <td className="p-4"><div className="h-4 w-20 bg-gray-200 animate-pulse rounded ml-auto" /></td>
                          <td className="p-4"><div className="h-4 w-12 bg-gray-200 animate-pulse rounded mx-auto" /></td>
                        </tr>
                      ))
                    : (recentRaw ?? []).map((sitting) => (
                        <tr key={sitting.sitting_date} className="border-b hover:bg-gray-50">
                          <td className="p-4 font-medium align-top">
                            <Link
                              to={`/sitting/${sitting.sitting_date}`}
                              className="text-navy hover:text-teal hover:underline"
                            >
                              {formatDate(sitting.sitting_date)}
                            </Link>
                            {sitting.summary_3_sentences && (
                              <p
                                className="text-xs font-normal text-gray-500 mt-1 line-clamp-1 max-w-md"
                                title={sitting.summary_3_sentences}
                              >
                                {sitting.summary_3_sentences}
                              </p>
                            )}
                          </td>
                          <td className="p-4 text-right text-gray-700">{formatNumber(sitting.speech_count)}</td>
                          <td className="p-4 text-right text-gray-700">{formatNumber(sitting.word_count)}</td>
                          <td className="p-4 text-center">
                            <a
                              href={hansardUrl(sitting.sitting_date)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-teal hover:underline text-xs"
                            >
                              <ExternalLink size={13} /> Hansard
                            </a>
                          </td>
                        </tr>
                      ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </section>

      {/* Navigation cards */}
      <section>
        <h2 className="text-2xl font-bold text-navy mb-4">Explore</h2>
        <div className="grid sm:grid-cols-3 gap-6">
          <Link to="/mp" className="group">
            <Card className="h-full hover:shadow-md transition-shadow border-2 hover:border-teal">
              <CardContent className="p-6 flex flex-col gap-3">
                <Users className="h-8 w-8 text-teal" />
                <h3 className="text-lg font-semibold text-navy">Members of Parliament</h3>
                <p className="text-sm text-gray-600">Browse all MPs and explore their parliamentary activity, speeches, and key topics.</p>
                <span className="flex items-center gap-1 text-teal text-sm font-medium group-hover:gap-2 transition-all">
                  Browse MPs <ArrowRight size={14} />
                </span>
              </CardContent>
            </Card>
          </Link>

          <Link to="/topics" className="group">
            <Card className="h-full hover:shadow-md transition-shadow border-2 hover:border-teal">
              <CardContent className="p-6 flex flex-col gap-3">
                <BookOpen className="h-8 w-8 text-teal" />
                <h3 className="text-lg font-semibold text-navy">Topic Explorer</h3>
                <p className="text-sm text-gray-600">Search and filter parliamentary debates by topic, date range, and section type.</p>
                <span className="flex items-center gap-1 text-teal text-sm font-medium group-hover:gap-2 transition-all">
                  Explore Topics <ArrowRight size={14} />
                </span>
              </CardContent>
            </Card>
          </Link>

          <Link to="/trends" className="group">
            <Card className="h-full hover:shadow-md transition-shadow border-2 hover:border-teal">
              <CardContent className="p-6 flex flex-col gap-3">
                <TrendingUp className="h-8 w-8 text-teal" />
                <h3 className="text-lg font-semibold text-navy">Trends</h3>
                <p className="text-sm text-gray-600">Visualise parliamentary activity over time — volume, intensity, and speaker diversity.</p>
                <span className="flex items-center gap-1 text-teal text-sm font-medium group-hover:gap-2 transition-all">
                  View Trends <ArrowRight size={14} />
                </span>
              </CardContent>
            </Card>
          </Link>
        </div>
      </section>
    </div>
  )
}
