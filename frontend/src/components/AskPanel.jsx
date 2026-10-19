import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Spin, Tag, Typography } from 'antd'
import { askStream, listDocuments, listStrategies } from '../api'
import ChunkGrid from './ChunkGrid'

export default function AskPanel() {
  const [strategies, setStrategies] = useState([])
  const [strategy, setStrategy] = useState('similarity')
  const [documents, setDocuments] = useState([])
  const [documentId, setDocumentId] = useState(null)
  const [question, setQuestion] = useState('')

  // idle -> routing -> retrieving -> answering -> idle
  const [phase, setPhase] = useState('idle')
  const [route, setRoute] = useState(null)
  const [chunks, setChunks] = useState(null)
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  const refreshDocuments = () =>
    listDocuments()
      .then((d) => setDocuments(d.documents))
      .catch(() => {})

  useEffect(() => {
    listStrategies()
      .then((d) => setStrategies(d.strategies))
      .catch((e) => setError(e.message))
    refreshDocuments()
    return () => abortRef.current?.abort()
  }, [])

  const handleAsk = async () => {
    abortRef.current = new AbortController()
    setPhase('routing')
    setRoute(null)
    setChunks(null)
    setAnswer('')
    setError(null)
    try {
      await askStream(
        { question: question.trim(), strategy, documentId },
        {
          signal: abortRef.current.signal,
          onRoute: (r) => {
            setRoute(r)
            setPhase(r === 'rag' ? 'retrieving' : 'answering')
          },
          onRetrieval: (c) => {
            setChunks(c)
            setPhase('answering')
          },
          onToken: (t) => setAnswer((prev) => prev + t),
        }
      )
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      setPhase('idle')
    }
  }

  const running = phase !== 'idle'
  const description = strategies.find((s) => s.id === strategy)?.description

  return (
    <>
      <Card title="Ask a question" style={{ marginBottom: 24 }}>
        <Space wrap style={{ marginBottom: 8 }}>
          <Select
            style={{ width: 280 }}
            value={strategy}
            onChange={setStrategy}
            disabled={running}
            options={strategies.map((s) => ({ value: s.id, label: s.label }))}
          />
          <Select
            style={{ width: 320 }}
            allowClear
            placeholder="All documents"
            value={documentId}
            onChange={(v) => setDocumentId(v ?? null)}
            onOpenChange={(open) => open && refreshDocuments()}
            disabled={running}
            options={documents.map((d) => ({
              value: d.document_id,
              label: `${d.filename} (${d.chunk_count} chunks)`,
            }))}
          />
        </Space>
        {description && (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            {description}
          </Typography.Paragraph>
        )}
        <Input.TextArea
          rows={3}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What are the payment terms?"
          disabled={running}
        />
        <Button
          type="primary"
          loading={running}
          disabled={!question.trim()}
          onClick={handleAsk}
          style={{ marginTop: 12 }}
        >
          Ask
        </Button>
        {error && <Alert type="error" message={error} showIcon style={{ marginTop: 16 }} />}
      </Card>

      {(phase === 'routing' || phase === 'retrieving') && (
        <Card style={{ marginBottom: 24 }}>
          <Spin
            tip={phase === 'routing' ? 'Understanding your question…' : 'Retrieving chunks…'}
            style={{ display: 'block', margin: 16 }}
          />
        </Card>
      )}

      {chunks && (
        <Card title={`Retrieved chunks (${chunks.length})`} style={{ marginBottom: 24 }}>
          {chunks.length ? (
            <ChunkGrid chunks={chunks} showSource />
          ) : (
            <Typography.Text type="secondary">No chunks matched this strategy.</Typography.Text>
          )}
        </Card>
      )}

      {(chunks || (route && route !== 'rag')) && (
        <Card
          title="Answer"
          extra={
            route === 'greeting' ? (
              <Tag color="blue">Greeting – no retrieval</Tag>
            ) : route === 'out_of_scope' ? (
              <Tag color="orange">Out of scope – no retrieval</Tag>
            ) : null
          }
        >
          {phase === 'answering' && !answer && <Spin tip="Generating answer…" />}
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
            {answer}
            {phase === 'answering' && answer && ' ▍'}
          </Typography.Paragraph>
        </Card>
      )}
    </>
  )
}
