import { useState, useEffect } from 'react'
import type { Achievement } from '../types'
import { api } from '../api'

export default function AchievementsScreen() {
  const [achievements, setAchievements] = useState<Achievement[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    api.getAchievements()
      .then(data => { setAchievements(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  if (loading) {
    return (
      <div>
        <header className="header"><h1>🏆 Достижения</h1></header>
        <div className="loading-wrap"><div className="spinner" /></div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <header className="header"><h1>🏆 Достижения</h1></header>
        <div className="error-banner">{error}</div>
      </div>
    )
  }

  const unlocked = achievements.filter(a => a.unlocked).length
  const total    = achievements.length
  const pct      = total > 0 ? Math.round((unlocked / total) * 100) : 0

  return (
    <div>
      <header className="header"><h1>🏆 Достижения</h1></header>
      <div className="achievements-screen">
        <div className="ach-progress-wrap">
          <div className="ach-progress-label">
            <span className="ach-title">Прогресс</span>
            <span className="ach-count">{unlocked} / {total} разблокировано</span>
          </div>
          <div className="progress-bar-track">
            <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
          </div>
        </div>

        <div className="ach-grid">
          {achievements.map(ach => (
            <div key={ach.key} className={`ach-card${ach.unlocked ? '' : ' locked'}`}>
              <span className="ach-emoji">{ach.unlocked ? ach.emoji : '🔒'}</span>
              <span className="ach-name">{ach.unlocked ? ach.name : '???'}</span>
              <span className="ach-desc">{ach.unlocked ? ach.desc : 'Продолжайте выполнять задачи!'}</span>
              {ach.unlocked
                ? <span className="ach-check">✓</span>
                : <span className="ach-lock">🔒</span>
              }
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
