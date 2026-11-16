import { useState } from 'react'
import { Alert, Button, Card, Spin, Upload } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { uploadPdf } from '../api'
import { DOC_TYPES } from '../labels'
import ChunkGrid from './ChunkGrid'

export default function UploadPanel({ onUploaded }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [showChunks, setShowChunks] = useState(true)

  const handleUpload = async (file) => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      setResult(await uploadPdf(file))
      setShowChunks(true)
      onUploaded?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
    return false // prevent antd's own upload
  }

  return (
    <Card title="Upload a PDF" style={{ marginBottom: 24 }}>
      <Upload.Dragger
        accept=".pdf"
        maxCount={1}
        showUploadList={false}
        disabled={loading}
        beforeUpload={handleUpload}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">Click or drag a PDF here</p>
      </Upload.Dragger>

      {loading && (
        <Spin
          tip="Extracting with Docling, classifying, chunking and embedding… this can take a minute"
          style={{ display: 'block', margin: 24 }}
        />
      )}
      {error && <Alert type="error" message={error} showIcon style={{ marginTop: 16 }} />}

      {result && (
        <>
          <Alert
            type="success"
            showIcon
            style={{ margin: '16px 0' }}
            message={`${result.filename} · ${DOC_TYPES[result.doc_type] ?? result.doc_type}: ${result.chunks_indexed} chunks indexed`}
            action={
              <Button size="small" onClick={() => setShowChunks((v) => !v)}>
                {showChunks ? 'Hide chunks' : 'Show chunks'}
              </Button>
            }
          />
          {showChunks && <ChunkGrid chunks={result.chunks} />}
        </>
      )}
    </Card>
  )
}
