import type { DatasetFile, DatasetRow } from '../data/stats'

export const S3_BASE = 'https://twrh.s3.ap-northeast-3.amazonaws.com/'

/** 資料集版本的釋出階段標記（data_ver 如「0.1 Beta」） */
export const RELEASE_STAGE: Record<string, string> = {
  beta: '本次資料集有新增欄位，但由於資料更新的限制，並非整個月的的物件都有此資料'
}

export type PeriodPrefix = '' | 'Q' | '0'

/** '3' → 'Q3' / '03'，年度資料（prefix 為空）不顯示期間 */
export function periodLabel(time: string, prefix: PeriodPrefix): string {
  return prefix ? time.padStart(2, prefix) : ''
}

export function downloadUrl(
  file: DatasetFile,
  row: DatasetRow,
  year: number,
  prefix: PeriodPrefix
): string {
  const config = file.download_url
  if (typeof config === 'string') {
    return config
  }
  if (config.isS3) {
    const period = periodLabel(row.time, prefix)
    const type = row.type === '原始資料' ? 'Raw' : 'Deduplicated'
    const format = (file.format ?? 'csv').toUpperCase()
    const fileName = `[${year}${period}][${format}][${type}] TW-Rental-Data.zip`
    return `${S3_BASE}${year}/${fileName}`
  }
  return ''
}

export function prettyFilesize(sizeByte: number): string {
  const units = ['B', 'KB', 'MB', 'GB']
  let size = sizeByte
  let unitIndex = 0
  while (size >= 1000 && unitIndex < units.length - 1) {
    size /= 1000
    unitIndex += 1
  }
  return `${size >= 100 ? Math.round(size) : size.toFixed(1)} ${units[unitIndex]}`
}

export function commentLines(row: DatasetRow): string[] {
  if (!row.comment) {
    return []
  }
  return Array.isArray(row.comment) ? row.comment : [row.comment]
}

const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;'
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (char) => HTML_ESCAPES[char]!)
}

/** 附註欄只用到 markdown 連結語法，逐一轉成 <a>，其餘文字 escape */
export function renderCommentHtml(line: string): string {
  let html = ''
  let cursor = 0
  const linkPattern = /\[([^\]]+)\]\(([^)\s]+)\)/g
  for (const match of line.matchAll(linkPattern)) {
    html += escapeHtml(line.slice(cursor, match.index))
    html += `<a class="text-tile-deep underline" href="${escapeHtml(match[2]!)}">${escapeHtml(match[1]!)}</a>`
    cursor = match.index + match[0].length
  }
  html += escapeHtml(line.slice(cursor))
  return html
}
