import { useState, useEffect } from 'react'
import type { Stats } from '../types'
import { api } from '../api'

function DonutChart({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  const r = 54
  const circ = 2 * Math.PI * r
  const offset = circ - (pct / 100) * circ

  return (
    <div className="stats-chart-wrap">
      <svg width="140" height="140" viewBox="0 0 140 140">
        <circle
          cx="70" cy="70" r={r}
          fill="none"
          stroke="rgba(0,0,0,0.07)"
          strokeWidth="14"
        />
        <circle
          cx="70" cy="70" r={r}
          fill="none"
          stroke="var(--btn)"
          strokeWidth="14"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 70 70)"
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
        <text x="70" y="66" textAnchor="middle" fontSize="26" fontWeight="700" fill="var(--text)">
          {pct}%
        </text>
        <text x="70" y="85" textAnchor="middle" fontSize="12" fill="var(--hint)">
          выполнено
        </text>
      </svg>
    </div>
  )
}

const STAT_CARDS = [
  { key: 'total',      icon: '📋', label: 'Всего' },
  { key: 'active',     icon: '⏳', label: 'Активных' },
  { key: 'done_all',   icon: '✅', label: 'Выполнено' },
  { key: 'overdue',    icon: '🔴', label: 'Просрочено' },
  { key: 'done_week',  icon: '📅', label: 'За неделю' },
  { key: 'done_month', icon: '📆', label: 'За месяц' },
  { key: 'streak',     icon: '🔥', label: 'Серия дней' },
  { key: 'best_streak',icon: '🏅', label: 'Лучшая серия' },
] as const

export default function StatsScreen() {
  const [stats, setStats]   = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

  useEffect(() => {
    api.getStats()
      .then(data => { setStats(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  if (loading) {
    return (
      <div>
        <header className="header"><h1>📊 Статистика</h1></header>
        <div className="loading-wrap"><div className="spinner" /></div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <header className="header"><h1>📊 Статистика</h1></header>
        <div className="error-banner">{error}</div>
      </div>
    )
  }

  if (!stats) return null

  return (
    <div>
      <header className="header"><h1>📊 Статистика</h1></header>
      <div className="stats-screen">
        <DonutChart done={stats.done_all} total={stats.total} />

        <div className="stats-grid">
          {STAT_CARDS.map(({ key, icon, label }) => (
            <div key={key} className="stat-card">
              <span className="stat-icon">{icon}</span>
              <span className="stat-value">{stats[key as keyof Stats]}</span>
              <span className="stat-label">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
