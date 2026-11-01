import { Layout, Tabs, Typography } from 'antd'
import DocumentsPanel from './components/DocumentsPanel'
import AskPanel from './components/AskPanel'

export default function App() {
  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <Layout.Content style={{ maxWidth: 1400, margin: '0 auto', padding: '8px 24px 24px', width: '100%' }}>
        <Typography.Title level={3} style={{ margin: '8px 0 0' }}>
          Financial Document RAG
        </Typography.Title>
        <Tabs
          items={[
            { key: 'documents', label: 'Documents', children: <DocumentsPanel /> },
            { key: 'ask', label: 'Ask', children: <AskPanel /> },
          ]}
        />
      </Layout.Content>
    </Layout>
  )
}
