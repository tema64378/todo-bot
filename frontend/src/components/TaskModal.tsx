import { useState, useEffect } from 'react'
import type { Task, Priority } from '../types'
import { api } from '../api'

interface Props {
  task?: Task | null
  onClose: () => void
  onSaved: (task: Task) => void
}

const CATEGORIES = ['Работа', 'Личное', 'Учёба', 'Здоровье', 'Финансы', 'Другое']
const CAT_EMOJI: Record<string, string> = {
  'Работа': '💼', 'Личное': '🏠', 'Учёба': '📚',
  'Здоровье': '💪', 'Финансы': '💰', 'Другое': '📌',
}

export default function TaskModal({ task, onClose, onSaved }: Props) {
  const [title, setTitle]       = useState(task?.title ?? '')
  const [priority, setPriority] = useState<Priority>(task?.priority ?? 'medium')
  const [category, setCategory] = useState(task?.category ?? 'Другое')
  const [deadline, setDeadline] = useState(task?.deadline ?? '')
  const [notes, setNotes]       = useState(task?.notes ?? '')
  const [saving, setSaving]     = useState(false)
  const [error, setError]       = useState('')

  useEffect(() => {
    // Prevent body scroll when modal is open
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const isEdit = Boolean(task)

  const handleSave = async () => {
    if (!title.trim()) {
      setError('Введите название задачи')
      return
    }
    setSaving(true)
    setError('')
    try {
      const payload = {
        title: title.trim(),
        priority,
        category,
        deadline: deadline || null,
        notes: notes.trim() || null,
      }
      let saved: Task
      if (isEdit && task) {
        saved = await api.updateTask(task.id, payload)
      } else {
        saved = await api.createTask(payload)
      }
      onSaved(saved)
    } catch (e: any) {
      setError(e.message ?? 'Ошибка сохранения')
      setSaving(false)
    }
  }

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div className="modal-sheet">
        <div className="modal-handle" />
        <div className="modal-header">
          <span className="modal-title">{isEdit ? 'Редактировать' : 'Новая задача'}</span>
          <button className="icon-btn" onClick={onClose} style={{ fontSize: 20 }}>✕</button>
        </div>

        <div className="modal-body">
          {/* Title */}
          <div className="form-group">
            <label className="form-label">Название</label>
            <input
              className="form-input"
              placeholder="Что нужно сделать?"
              value={title}
              onChange={e => setTitle(e.target.value)}
              autoFocus
            />
          </div>

          {/* Priority */}
          <div className="form-group">
            <label className="form-label">Приоритет</label>
            <div className="priority-group">
              {(['high', 'medium', 'low'] as Priority[]).map(p => (
                <button
                  key={p}
                  className={`pri-btn${priority === p ? ' active ' + p : ''}`}
                  onClick={() => setPriority(p)}
                >
                  {p === 'high' ? '🔴 Высокий' : p === 'medium' ? '🟡 Средний' : '🟢 Низкий'}
                </button>
              ))}
            </div>
          </div>

          {/* Category */}
          <div className="form-group">
            <label className="form-label">Категория</label>
            <div className="cat-scroll">
              {CATEGORIES.map(c => (
                <button
                  key={c}
                  className={`cat-chip${category === c ? ' active' : ''}`}
                  onClick={() => setCategory(c)}
                >
                  {CAT_EMOJI[c]} {c}
                </button>
              ))}
            </div>
          </div>

          {/* Deadline */}
          <div className="form-group">
            <label className="form-label">Дедлайн</label>
            <input
              className="form-input"
              type="date"
              value={deadline}
              onChange={e => setDeadline(e.target.value)}
            />
          </div>

          {/* Notes */}
          <div className="form-group">
            <label className="form-label">Заметки</label>
            <textarea
              className="form-textarea"
              placeholder="Дополнительные заметки..."
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={3}
            />
          </div>

          {error && <div className="error-banner">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose}>Отмена</button>
          <button className="btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать'}
          </button>
        </div>
      </div>
    </div>
  )
}
