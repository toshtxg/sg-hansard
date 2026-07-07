import { Routes, Route } from 'react-router-dom'
import { Shell } from '@/components/layout/Shell'
import { Overview } from '@/pages/Overview'
import { MPList } from '@/pages/MPList'
import { MPDetail } from '@/pages/MPDetail'
import { TopicExplorer } from '@/pages/TopicExplorer'
import { SittingDetail } from '@/pages/SittingDetail'
import { Trends } from '@/pages/Trends'
import { About } from '@/pages/About'

function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<Overview />} />
        <Route path="/mp" element={<MPList />} />
        <Route path="/mp/:name" element={<MPDetail />} />
        <Route path="/topics" element={<TopicExplorer />} />
        <Route path="/sitting/:date" element={<SittingDetail />} />
        <Route path="/trends" element={<Trends />} />
        <Route path="/about" element={<About />} />
      </Route>
    </Routes>
  )
}

export default App
