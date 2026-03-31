import { useState, useEffect, useCallback } from 'react'
import type { Task, TaskFilter } from '../types'
import { api } from '../api'
import TaskCard from '../components/TaskCard'
import TaskModal from '../components/TaskModal'

interface Props {
  editTask: Task | null
  setEditTask: (t: Task | null) => void
  showCreate: boolean
  setShowCreate: (v: boolean) => void
}

const FILTER_LABELS: { id: TaskFilter; label: string }[] = [
  { id: 'all',      label: 'Все' },
  { id: 'today',    label: 'Сегодня' },
  { id: 'upcoming', label: 'Предстоящие' },
]

function isToday(dl: string | null): boolean {
  if (!dl) return false
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(dl + 'T00:00:00')
  return d.getTime() === today.getTime()
}

function isUpcoming(dl: string | null): boolean {
  if (!dl) return false
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(dl + 'T00:00:00')
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000)
  return diff > 0 && diff <= 7
}

function Toast({ message, onDone }: { message: string; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 2500)
    return () => clearTimeout(t)
  }, [onDone])
  return <div className="toast">{message}</div>
}

export default function TasksScreen({ editTask, setEditTask, showCreate, setShowCreate }: Props) {
  const [tasks, setTasks]       = useState<Task[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [filter, setFilter]     = useState<TaskFilter>('all')
  const [toast, setToast]       = useState('')

  const load = useCallback(async () => {
    try {
      const data = await api.getTasks()
      setTasks(data)
      setError('')
    } catch (e: any) {
      setError(e.message ?? 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSaved = (saved: Task) => {
    setTasks(prev => {
      const idx = prev.findIndex(t => t.id === saved.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = saved
        return next
      }
      return [saved, ...prev]
    })
    setEditTask(null)
    setShowCreate(false)
    setToast(saved.id && tasks.find(t => t.id === saved.id) ? '✅ Задача обновлена' : '✅ Задача создана')
  }

  const handleToggleDone = (updated: Task) => {
    setTasks(prev => prev.map(t => t.id === updated.id ? { ...t, done: updated.done } : t))
    if (updated.done) setToast('🎉 Задача выполнена!')
  }

  const handleDeleted = (id: number) => {
    setTasks(prev => prev.filter(t => t.id !== id))
    setToast('🗑 Задача удалена')
  }

  const filtered = tasks.filter(t => {
    if (filter === 'today')    return isToday(t.deadline)
    if (filter === 'upcoming') return isUpcoming(t.deadline)
    return true
  })

  const active   = filtered.filter(t => !t.done)
  const done     = filtered.filter(t => t.done)
  const displayed = [...active, ...done]

  return (
    <>
      <header className="header">
        <h1>📋 Мои задачи</h1>
      </header>

      <div className="filter-tabs">
        {FILTER_LABELS.map(f => (
          <button
            key={f.id}
            className={`filter-tab${filter === f.id ? ' active' : ''}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="loading-wrap">
          <div className="spinner" />
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      {!loading && !error && displayed.length === 0 && (
        <div className="empty-state">
          <span className="empty-icon">
            {filter === 'today' ? '📆' : filter === 'upcoming' ? '📅' : '✨'}
          </span>
          <h3>
            {filter === 'today'
              ? 'На сегодня задач нет'
              : filter === 'upcoming'
              ? 'Предстоящих задач нет'
              : 'Список пуст'}
          </h3>
          <p>
            {filter === 'all'
              ? 'Нажмите + чтобы добавить первую задачу'
              : 'Задачи с дедлайном появятся здесь'}
          </p>
        </div>
      )}

      {!loading && displayed.length > 0 && (
        <div className="card-list">
          {displayed.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              onEdit={setEditTask}
              onDeleted={handleDeleted}
              onToggleDone={handleToggleDone}
            />
          ))}
        </div>
      )}

      <button className="fab" onClick={() => setShowCreate(true)}>+</button>

      {(showCreate || editTask) && (
        <TaskModal
          task={editTask}
          onClose={() => { setShowCreate(false); setEditTask(null) }}
          onSaved={handleSaved}
        />
      )}

      {toast && <Toast message={toast} onDone={() => setToast('')} />}
    </>
  )
}
