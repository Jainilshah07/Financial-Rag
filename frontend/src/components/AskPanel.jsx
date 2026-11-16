import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Col, Input, Row, Select, Typography } from 'antd'
import { askStream, getOptions, listDocuments } from '../api'
import { citedPages } from '../citations'
import { CHUNKER_HELP, DOC_TYPES, DOCUMENT_HELP, METHOD_HELP } from '../labels'
import PipelinePanel from './PipelinePanel'
import RetrievedChunks from './RetrievedChunks'

// phase: idle -> retrieving -> answering -> finished (or error)
const INITIAL_RUN = {
  phase: 'idle',
  chunks: null,
  trace: null, // dense_intent only: intent, filters applied, fallback
  answer: '',
  tokens: 0,
  retrievalMs: null,
  doneMs: null,
  log: [],
}

const RUNNING = ['retrieving', 'answering']

function withLog(log, name, p) {
  const text = name === 'retrieval' ? `${p.chunks.length} chunks · ${p.chunker} · ${p.method}` : ''

  if (name === 'token') {
    // collapse the token stream into one updating line
    const last = log[log.length - 1]
    const count = last?.name === 'token' ? last.count + 1 : 1
    const entry = { name, ms: p.elapsed_ms, count, text: `×${count}` }
    return last?.name === 'token' ? [...log.slice(0, -1), entry] : [...log, entry]
  }
  return [...log, { name, ms: p.elapsed_ms, text }]
}

function reduceEvent(run, name, p) {
  const log = withLog(run.log, name, p)
  switch (name) {
    case 'retrieval':
      return { ...run, log, chunks: p.chunks, trace: p.trace, retrievalMs: p.elapsed_ms, phase: 'answering' }
    case 'token':
      return { ...run, log, answer: run.answer + p.text, tokens: run.tokens + 1 }
    case 'done':
      return { ...run, log, doneMs: p.elapsed_ms, phase: 'finished' }
    default:
      return run
  }
}

// A labelled control with a one-line explanation of the current choice underneath.
function Field({ label, help, width, grow, children }) {
  return (
    <div style={grow ? { flex: '1 1 320px' } : { width }}>
      <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
        {label}
      </Typography.Text>
      {children}
      {help && (
        <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4 }}>
          {help}
        </Typography.Text>
      )}
    </div>
  )
}

function OptionWithHelp({ label, help }) {
  return (
    <div style={{ whiteSpace: 'normal' }}>
      <div>{label}</div>
      {help && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {help}
        </Typography.Text>
      )}
    </div>
  )
}

export default function AskPanel() {
  const [options, setOptions] = useState({ chunkers: [], methods: [] })
  const [chunker, setChunker] = useState(null)
  const [method, setMethod] = useState(null)
  const [documents, setDocuments] = useState([])
  const [documentId, setDocumentId] = useState(null)
  const [question, setQuestion] = useState('')
  const [run, setRun] = useState(INITIAL_RUN)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)
  const answerEndRef = useRef(null)

  const refreshDocuments = () =>
    listDocuments()
      .then((d) => setDocuments(d.documents))
      .catch(() => {})

  useEffect(() => {
    getOptions()
      .then((d) => {
        setOptions(d)
        setChunker(d.defaults.chunker)
        setMethod(d.defaults.method)
      })
      .catch((e) => setError(e.message))
    refreshDocuments()
    return () => abortRef.current?.abort()
  }, [])

  // keep the newest streamed text in view inside the answer panel
  useEffect(() => {
    answerEndRef.current?.scrollIntoView({ block: 'nearest' })
  }, [run.answer])

  const handleAsk = async () => {
    abortRef.current = new AbortController()
    setRun({ ...INITIAL_RUN, phase: 'retrieving' })
    setError(null)
    try {
      await askStream(
        { question: question.trim(), chunker, method, documentId },
        {
          signal: abortRef.current.signal,
          onEvent: (name, payload) => setRun((r) => reduceEvent(r, name, payload)),
        }
      )
    } catch (e) {
      if (e.name !== 'AbortError') {
        setError(e.message)
        setRun((r) => ({ ...r, phase: 'error' }))
      }
    }
  }

  // (file, page) pairs the answer cites -> highlight those chunk cards
  const cited = useMemo(() => citedPages(run.answer), [run.answer])

  const running = RUNNING.includes(run.phase)
  const label = (list, id) => list.find((o) => o.id === id)?.label ?? ''
  const strategyLabel = [label(options.chunkers, chunker), label(options.methods, method)].filter(Boolean).join(' · ')

  return (
    <>
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <Field label="Chunker" help={CHUNKER_HELP[chunker]} width={220}>
            <Select
              style={{ width: '100%' }}
              aria-label="Chunker"
              value={chunker}
              onChange={setChunker}
              disabled={running}
              popupMatchSelectWidth={360}
              optionRender={(o) => <OptionWithHelp label={o.label} help={CHUNKER_HELP[o.value]} />}
              options={options.chunkers.map((o) => ({ value: o.id, label: o.label }))}
            />
          </Field>
          <Field label="Retrieval method" help={METHOD_HELP[method]} width={280}>
            <Select
              style={{ width: '100%' }}
              aria-label="Retrieval method"
              value={method}
              onChange={setMethod}
              disabled={running}
              popupMatchSelectWidth={420}
              optionRender={(o) => <OptionWithHelp label={o.label} help={METHOD_HELP[o.value]} />}
              options={options.methods.map((o) => ({ value: o.id, label: o.label }))}
            />
          </Field>
          <Field label="Document" help={DOCUMENT_HELP} width={300}>
            <Select
              style={{ width: '100%' }}
              aria-label="Document"
              allowClear
              placeholder="All documents"
              value={documentId}
              onChange={(v) => setDocumentId(v ?? null)}
              onOpenChange={(open) => open && refreshDocuments()}
              disabled={running}
              options={documents.map((d) => ({
                value: d.document_id,
                label: `${d.filename} · ${DOC_TYPES[d.doc_type] ?? d.doc_type} (${d.chunkers?.[chunker] ?? 0} chunks)`,
              }))}
            />
          </Field>
          <Field label="Question" grow>
            <div style={{ display: 'flex', gap: 8 }}>
              <Input
                aria-label="Question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onPressEnter={() => !running && question.trim() && chunker && handleAsk()}
                placeholder="Ask about your documents, e.g. What are the payment terms?"
                disabled={running}
              />
              <Button type="primary" loading={running} disabled={!question.trim() || !chunker} onClick={handleAsk}>
                Ask
              </Button>
            </div>
          </Field>
        </div>
        {error && <Alert type="error" message={error} showIcon style={{ marginTop: 8 }} />}
      </Card>

      <Row gutter={16} className="workbench">
        <Col xs={24} lg={8} style={{ height: '100%' }}>
          <PipelinePanel run={run} strategyLabel={strategyLabel} />
        </Col>
        <Col xs={24} lg={16} style={{ height: '100%' }}>
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* chunks take all the space the answer doesn't need */}
            <div style={{ flex: 1, minHeight: 0 }}>
              <RetrievedChunks run={run} cited={cited} />
            </div>
            {/* answer grows with its content, up to ~40% of the workbench, then scrolls */}
            <div style={{ flex: '0 0 auto' }}>
              <Card
                title="Answer"
                className="answer-card"
                style={{ display: 'flex', flexDirection: 'column' }}
                styles={{ body: { flex: 1, minHeight: 0, overflow: 'auto' } }}
              >
                {run.answer ? (
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {run.answer}
                    {run.phase === 'answering' && <span className="cursor">▍</span>}
                  </Typography.Paragraph>
                ) : (
                  <Typography.Text type="secondary">
                    {run.phase === 'idle' ? 'The answer will stream in here' : 'Waiting for the answer…'}
                  </Typography.Text>
                )}
                <div ref={answerEndRef} />
              </Card>
            </div>
          </div>
        </Col>
      </Row>
    </>
  )
}
