import { Card, Collapse, Steps, Typography } from 'antd'
import { LoadingOutlined } from '@ant-design/icons'
import { DOC_TYPES } from '../labels'

const formatMs = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`)
const typeName = (t) => DOC_TYPES[t] ?? t

// What dense_intent actually did (from the API's trace). A filter is listed only if it produced the results.
function traceLines(trace) {
  if (!trace) return []
  if (trace.intent == null) return ['One document selected: no intent classification, no filters']
  const filters = [
    trace.type_filter && `document type = ${typeName(trace.type_filter)}`,
    trace.number_filter && 'document number',
  ].filter(Boolean)
  return [
    `Question intent: ${trace.intent_failed ? 'classification failed' : typeName(trace.intent)}`,
    `Filters applied: ${filters.join(', ') || 'none'}`,
    ...(trace.fallback ? [`Fallback: no document-type filter (${trace.fallback.replaceAll('_', ' ')})`] : []),
  ]
}

// Derive the two pipeline steps from the state of the current run.
function buildSteps(run, strategyLabel) {
  const { phase, chunks, tokens, retrievalMs, doneMs } = run
  const failed = phase === 'error'
  const finished = phase === 'finished'

  const retrieve = !chunks
    ? { status: phase === 'idle' ? 'wait' : failed ? 'error' : 'active', detail: `${strategyLabel || 'Search'}…` }
    : { status: 'done', detail: `${strategyLabel} · ${chunks.length} chunks`, lines: traceLines(run.trace), ms: retrievalMs }

  let generate
  if (!chunks) generate = { status: 'wait', detail: 'LLM answers from the chunks' }
  else if (finished) generate = { status: 'done', detail: `${tokens} stream events`, ms: doneMs - retrievalMs }
  else generate = { status: failed ? 'error' : 'active', detail: tokens ? `Streaming… ${tokens} events` : 'Waiting for first token…' }

  return [
    { title: 'Retrieve', ...retrieve },
    { title: 'Generate', ...generate },
  ]
}

const STATUS = { wait: 'wait', active: 'process', done: 'finish', error: 'error' }

export default function PipelinePanel({ run, strategyLabel }) {
  const steps = buildSteps(run, strategyLabel)

  const items = steps.map((s) => ({
    status: STATUS[s.status],
    icon: s.status === 'active' ? <LoadingOutlined /> : undefined,
    title: (
      <span>
        {s.title}
        {s.ms != null && (
          <Typography.Text type="secondary" style={{ marginLeft: 8, fontWeight: 400 }}>
            {formatMs(s.ms)}
          </Typography.Text>
        )}
      </span>
    ),
    description: (
      <>
        <Typography.Text type="secondary">{s.detail}</Typography.Text>
        {s.lines?.map((line) => (
          <div key={line}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{line}</Typography.Text>
          </div>
        ))}
      </>
    ),
  }))

  return (
    <Card
      title="Pipeline"
      style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
      styles={{ body: { flex: 1, minHeight: 0, overflow: 'auto' } }}
    >
      <Steps orientation="vertical" size="small" items={items} />

      <Collapse
        ghost
        size="small"
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'log',
            label: `Raw SSE events (${run.log.length})`,
            children: run.log.length ? (
              <div style={{ fontFamily: 'monospace', fontSize: 12, lineHeight: 1.7 }}>
                {run.log.map((e, i) => (
                  <div key={i}>
                    <span style={{ color: '#8c8c8c' }}>{String(e.ms).padStart(5)}ms</span>{' '}
                    <b>{e.name}</b> <span style={{ color: '#595959' }}>{e.text}</span>
                  </div>
                ))}
              </div>
            ) : (
              <Typography.Text type="secondary">No events yet.</Typography.Text>
            ),
          },
        ]}
      />
    </Card>
  )
}
