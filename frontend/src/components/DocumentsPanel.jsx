import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Popconfirm, Segmented, Spin, Table, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { deleteDocument, getDocumentChunks, listDocuments } from '../api'
import ChunkGrid from './ChunkGrid'
import UploadPanel from './UploadPanel'

const DOC_TYPES = { purchase_order: 'Purchase order', invoice: 'Invoice', unknown: 'Unknown' }
const STATUS_COLORS = { ingested: 'green', pending: 'blue', needs_ocr: 'orange', empty: 'default', failed: 'red' }

function DocumentDetail({ doc, onBack }) {
  // chunkers this document was ingested with, structure-aware first
  const chunkers = Object.keys(doc.chunkers ?? {}).sort((a, b) => (a === 'structure_ctx' ? -1 : b === 'structure_ctx' ? 1 : 0))
  const [chunker, setChunker] = useState(chunkers[0] ?? null)
  const [chunks, setChunks] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!chunker) return
    setChunks(null)
    setError(null)
    getDocumentChunks(doc.document_id, chunker)
      .then((data) => setChunks(data.chunks))
      .catch((e) => setError(e.message))
  }, [doc.document_id, chunker])

  return (
    <Card
      title={
        <>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack} />
          {doc.filename}
        </>
      }
      extra={
        chunkers.length > 1 ? (
          <Segmented
            value={chunker}
            onChange={setChunker}
            options={chunkers.map((c) => ({ value: c, label: `${c} (${doc.chunkers[c]})` }))}
          />
        ) : (
          <Typography.Text type="secondary">{chunker ? `${doc.chunkers[chunker]} chunks · ${chunker}` : 'No chunks'}</Typography.Text>
        )
      }
    >
      {error && <Alert type="error" message={error} showIcon />}
      {chunker && !chunks && !error && <Spin style={{ display: 'block', margin: 24 }} />}
      {chunks && <ChunkGrid chunks={chunks} />}
    </Card>
  )
}

const makeColumns = (onDelete) => [
  { title: 'Document', dataIndex: 'filename', key: 'filename' },
  { title: 'Type', dataIndex: 'doc_type', key: 'doc_type', width: 140, render: (v) => DOC_TYPES[v] ?? v },
  { title: 'Number', dataIndex: 'doc_number', key: 'doc_number', width: 170, render: (v) => v ?? '—' },
  {
    title: 'Status',
    dataIndex: 'status',
    key: 'status',
    width: 110,
    render: (v) => <Tag color={STATUS_COLORS[v]}>{v}</Tag>,
  },
  { title: 'Chunks', dataIndex: 'chunk_count', key: 'chunk_count', width: 90 },
  { title: 'Pages', dataIndex: 'page_count', key: 'page_count', width: 80 },
  {
    title: 'Uploaded',
    dataIndex: 'uploaded_at',
    key: 'uploaded_at',
    width: 200,
    render: (v) => (v ? new Date(v).toLocaleString() : '—'),
  },
  {
    title: '',
    key: 'actions',
    width: 60,
    render: (_, doc) => (
      // stop the click so deleting doesn't also open the document
      <span onClick={(e) => e.stopPropagation()}>
        <Popconfirm
          title="Delete this document?"
          description="Its pages and chunks are removed from the database."
          okText="Delete"
          okButtonProps={{ danger: true }}
          onConfirm={() => onDelete(doc)}
        >
          <Button type="text" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      </span>
    ),
  },
]

export default function DocumentsPanel() {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setDocuments((await listDocuments()).documents)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleDelete = async (doc) => {
    try {
      await deleteDocument(doc.document_id)
      await refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  if (selected) {
    return <DocumentDetail doc={selected} onBack={() => setSelected(null)} />
  }

  return (
    <>
      <UploadPanel onUploaded={refresh} />
      <Card
        title="Processed documents"
        extra={<Button icon={<ReloadOutlined />} onClick={refresh} loading={loading} />}
      >
        {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}
        <Table
          rowKey="document_id"
          columns={makeColumns(handleDelete)}
          dataSource={documents}
          loading={loading}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          onRow={(doc) => ({ onClick: () => setSelected(doc), style: { cursor: 'pointer' } })}
          locale={{ emptyText: 'No documents processed yet' }}
        />
      </Card>
    </>
  )
}
