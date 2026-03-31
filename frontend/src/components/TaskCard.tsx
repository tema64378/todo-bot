import { useState } from 'react'
import type { Task } from '../types'
import { api } from '../api'

interface Props {
  task: Task
  onEdit: (task: Task) => void
  onDeleted: (id: number) => void
  onToggleDone: (task: Task) => void
}

function formatDeadline(deadline: string | null): { label: string; cls: string } | null {
  if (!deadline) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(deadline + 'T00:00:00')
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000)

  if (diff < 0)  return { label: `Просрочено ${Math.abs(diff)} дн.`, cls: 'overdue' }
  if (diff === 0) return { label: 'Сегодня', cls: 'today' }
  if (diff === 1) return { label: 'Завтра', cls: '' }
  if (diff < 7)   return { label: `${diff} дн.`, cls: '' }
  return {
    label: d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }),
    cls: '',
  }
}

const CAT_EMOJI: Record<string, string> = {
  'Работа': '💼', 'Личное': '🏠', 'Учёба': '📚',
  'Здоровье': '💪', 'Финансы': '💰', 'Другое': '📌',
}

export default function TaskCard({ task, onEdit, onDeleted, onToggleDone }: Props) {
  const [completing, setCompleting] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const tg = (window as any).Telegram?.WebApp

  const handleDone = async () => {
    if (completing) return
    setCompleting(true)
    try {
      await api.markDone(task.id)
      tg?.HapticFeedback?.notificationOccurred('success')
      onToggleDone({ ...task, done: true })
    } catch {
      setCompleting(false)
    }
  }

  const handleUndone = async () => {
    try {
      await api.markUndone(task.id)
      onToggleDone({ ...task, done: false })
    } catch {}
  }

  const handleDelete = async () => {
    if (deleting) return
    setDeleting(true)
    try {
      await api.deleteTask(task.id)
      tg?.HapticFeedback?.notificationOccurred('warning')
      onDeleted(task.id)
    } catch {
      setDeleting(false)
    }
  }

  const dl = formatDeadline(task.deadline)
  const tags = task.tags ? task.tags.split(',').map(t => t.trim()).filter(Boolean) : []

  return (
    <div className={`task-card${task.done ? ' done' : ''}${completing ? ' completing' : ''}`}>
      <div className={`priority-bar ${task.priority}`} />
      <div className="task-body">
        <div className={`task-title${task.done ? ' strikethrough' : ''}`}>{task.title}</div>
        <div className="task-meta">
          {task.category && (
            <span className="chip chip-cat">
              {CAT_EMOJI[task.category] ?? '📌'} {task.category}
            </span>
          )}
          {dl && (
            <span className={`chip chip-deadline${dl.cls ? ' ' + dl.cls : ''}`}>
              📅 {dl.label}
            </span>
          )}
          {tags.map(tag => (
            <span key={tag} className="chip chip-tag">#{tag}</span>
          ))}
        </div>
      </div>
      <div className="task-actions">
        {task.done ? (
          <button className="icon-btn undone-btn" onClick={handleUndone} title="Вернуть">
            ↩️
          </button>
        ) : (
          <button className="icon-btn done-btn" onClick={handleDone} title="Выполнено">
            ✅
          </button>
        )}
        <button className="icon-btn" onClick={() => onEdit(task)} title="Редактировать">
          ✏️
        </button>
        <button className="icon-btn delete-btn" onClick={handleDelete} title="Удалить">
          🗑
        </button>
      </div>
    </div>
  )
}
