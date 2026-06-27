import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatNumber(n: number | null | undefined): string {
  if (n == null) return '—'
  return new Intl.NumberFormat().format(n)
}

export function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  // sitting_date is a calendar date (no time/zone). Render it in UTC so the day
  // doesn't shift backwards for viewers in timezones behind UTC.
  return new Date(d).toLocaleDateString('en-SG', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
}

export function hansardUrl(sittingDate: string): string {
  // Convert YYYY-MM-DD → https://sprs.parl.gov.sg/search/#/fullreport?sittingdate=DD-MM-YYYY
  const [year, month, day] = sittingDate.split('-')
  return `https://sprs.parl.gov.sg/search/#/fullreport?sittingdate=${day}-${month}-${year}`
}

export function sectionTypeLabel(code: string): string {
  const labels: Record<string, string> = {
    OS: 'Oral Speech',
    OA: 'Oral Answer',
    WA: 'Written Answer',
    WANA: 'Written Answer (Not Answered)',
    BP: 'Bill Proceedings',
    BI: 'Bill Introduction',
    WS: 'Written Statement',
  }
  return labels[code] ?? code
}
