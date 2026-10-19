import { Card, Col, Row, Tag, Typography } from 'antd'

function ChunkCard({ chunk, showSource }) {
  return (
    <Card
      size="small"
      title={`Chunk #${chunk.index}`}
      extra={<Typography.Text type="secondary">{chunk.text.length} chars</Typography.Text>}
      style={{ height: '100%' }}
    >
      <div style={{ marginBottom: 8 }}>
        {chunk.score != null && (
          <Tag color="gold">
            {chunk.score_label} {chunk.score}
          </Tag>
        )}
        {showSource && <Tag color="purple">{chunk.filename}</Tag>}
        <Tag color="blue">Page {chunk.page}</Tag>
        <Tag color={chunk.chunk_type === 'numbered_section' ? 'green' : 'default'}>
          {chunk.chunk_type}
        </Tag>
        <Tag>{chunk.section}</Tag>
      </div>
      <Typography.Paragraph
        ellipsis={{ rows: 5, expandable: 'collapsible' }}
        style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}
      >
        {chunk.text}
      </Typography.Paragraph>
    </Card>
  )
}

export default function ChunkGrid({ chunks, showSource = false }) {
  return (
    <Row gutter={[16, 16]}>
      {chunks.map((c) => (
        <Col key={c.point_id ?? c.index} xs={24} md={12} lg={8}>
          <ChunkCard chunk={c} showSource={showSource} />
        </Col>
      ))}
    </Row>
  )
}
