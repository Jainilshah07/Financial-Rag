import { useState } from 'react'
import { Card, Drawer, Empty, Progress, Skeleton, Tag, Typography } from 'antd'

const CARD_WIDTH = 280

function ChunkTags({ chunk }) {
  return (
    <>
      <Tag color="purple">{chunk.filename}</Tag>
      <Tag color="blue">Page {chunk.page}</Tag>
      {chunk.section && <Tag>{chunk.section}</Tag>}
    </>
  )
}

function ChunkCard({ chunk, percent, cited, delay, onOpen }) {
  return (
    <Card
      hoverable
      size="small"
      className="chunk-in"
      onClick={onOpen}
      title={`#${chunk.index}`}
      extra={
        <Typography.Text type="secondary">
          {chunk.score_label} {chunk.score}
        </Typography.Text>
      }
      style={{
        flex: `0 0 ${CARD_WIDTH}px`,
        width: CARD_WIDTH,
        animationDelay: `${delay}ms`,
        borderColor: cited ? '#1677ff' : undefined,
        boxShadow: cited ? '0 0 0 2px rgba(22,119,255,.25)' : undefined,
        transition: 'box-shadow .3s, border-color .3s',
      }}
    >
      <Progress percent={percent} showInfo={false} size="small" strokeColor="#faad14" />
      <div style={{ margin: '4px 0 8px' }}>
        <Tag color="blue">Page {chunk.page}</Tag>
        {chunk.section && <Tag>{chunk.section}</Tag>}
      </div>
      <Typography.Paragraph
        ellipsis={{ rows: 4 }}
        style={{ whiteSpace: 'pre-wrap', marginBottom: 0, fontSize: 13 }}
      >
        {chunk.text}
      </Typography.Paragraph>
    </Card>
  )
}

function Placeholder({ children }) {
  return (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={children} />
    </div>
  )
}

export default function RetrievedChunks({ run, citedPages }) {
  const [open, setOpen] = useState(null)
  const { phase, chunks } = run

  let body
  if (phase === 'idle' && !chunks) {
    body = <Placeholder>Retrieved chunks will appear here</Placeholder>
  } else if (!chunks) {
    // retrieving: skeleton cards keep the layout stable
    body = (
      <div style={{ display: 'flex', gap: 12 }}>
        {[0, 1, 2, 3].map((i) => (
          <Card key={i} size="small" style={{ flex: `0 0 ${CARD_WIDTH}px` }}>
            <Skeleton active paragraph={{ rows: 4 }} />
          </Card>
        ))}
      </div>
    )
  } else if (!chunks.length) {
    body = <Placeholder>No chunks matched this chunker and method</Placeholder>
  } else {
    const max = Math.max(...chunks.map((c) => c.score))
    body = (
      <div style={{ display: 'flex', gap: 12, paddingBottom: 8 }}>
        {chunks.map((c, i) => (
          <ChunkCard
            key={c.chunk_id}
            chunk={c}
            percent={Math.round((c.score_label === 'cosine' ? c.score : c.score / max) * 100)}
            cited={citedPages.has(c.page)}
            delay={i * 120}
            onOpen={() => setOpen(c)}
          />
        ))}
      </div>
    )
  }

  return (
    <>
      <Card
        title={`Retrieved chunks${chunks ? ` (${chunks.length})` : ''}`}
        extra={
          citedPages.size > 0 && <Typography.Text type="secondary">Blue outline = page cited in answer</Typography.Text>
        }
        style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
        styles={{ body: { flex: 1, minHeight: 0, overflow: 'auto' } }}
      >
        {body}
      </Card>

      <Drawer
        open={!!open}
        onClose={() => setOpen(null)}
        width={520}
        title={open && `Chunk #${open.index} · ${open.score_label} ${open.score}`}
      >
        {open && (
          <>
            <div style={{ marginBottom: 12 }}>
              <ChunkTags chunk={open} />
            </div>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{open.text}</Typography.Paragraph>
          </>
        )}
      </Drawer>
    </>
  )
}
