import { useState } from 'react'
import type { Tab, Task } from './types'
import BottomNav from './components/BottomNav'
import TasksScreen from './screens/TasksScreen'
import StatsScreen from './screens/StatsScreen'
import AchievementsScreen from './screens/AchievementsScreen'

export default function App() {
  const [tab, setTab] = useState<Tab>('tasks')
  const [editTask, setEditTask] = useState<Task | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  return (
    <div className="app">
      <div className="screen">
        {tab === 'tasks' && (
          <TasksScreen
            editTask={editTask}
            setEditTask={setEditTask}
            showCreate={showCreate}
            setShowCreate={setShowCreate}
          />
        )}
        {tab === 'stats' && <StatsScreen />}
        {tab === 'achievements' && <AchievementsScreen />}
      </div>
      <BottomNav activeTab={tab} onTabChange={setTab} />
    </div>
  )
}
