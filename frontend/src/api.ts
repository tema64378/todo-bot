import type { Task, Stats, Achievement } from './types'

const tg = (window as any).Telegram?.WebApp
const initData: string = tg?.initData || ''

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Init-Data': initData,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  getTasks: () => req<Task[]>('GET', '/tasks'),
  createTask: (data: Partial<Task>) => req<Task>('POST', '/tasks', data),
  updateTask: (id: number, data: Partial<Task>) => req<Task>('PUT', `/tasks/${id}`, data),
  deleteTask: (id: number) => req<void>('DELETE', `/tasks/${id}`),
  markDone: (id: number) => req<{ task: Task; new_achievements: string[] }>('POST', `/tasks/${id}/done`),
  markUndone: (id: number) => req<void>('POST', `/tasks/${id}/undone`),
  getStats: () => req<Stats>('GET', '/stats'),
  getAchievements: () => req<Achievement[]>('GET', '/achievements'),
}
