export interface Task {
  id: number
  title: string
  priority: 'high' | 'medium' | 'low'
  category: string
  tags: string | null
  deadline: string | null
  deadline_time: string | null
  remind_at: string | null
  notes: string | null
  repeat: string
  done: boolean
  completed_at: string | null
  created_at: string
}

export interface Stats {
  total: number
  active: number
  done_all: number
  done_week: number
  done_month: number
  overdue: number
  streak: number
  best_streak: number
}

export interface Achievement {
  key: string
  emoji: string
  name: string
  desc: string
  unlocked: boolean
}

export type Tab = 'tasks' | 'stats' | 'achievements'
export type TaskFilter = 'all' | 'today' | 'upcoming'
export type Priority = 'high' | 'medium' | 'low'
