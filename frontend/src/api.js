const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function errorMessage(res) {
  const data = await res.json().catch(() => ({}))
  return typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`
}

async function request(path, options) {
  const res = await fetch(`${BASE_URL}${path}`, options)
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

export function uploadPdf(file) {
  const form = new FormData()
  form.append('file', file)
  return request('/upload', { method: 'POST', body: form })
}

export function listDocuments() {
  return request('/documents')
}

export function getDocumentChunks(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}/chunks`)
}

export function deleteDocument(documentId) {
  return request(`/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' })
}

export function listStrategies() {
  return request('/strategies')
}

// POST /ask streams Server-Sent Events: `route` (rag | greeting | out_of_scope),
// `retrieval` (chunks, rag only), `token` (answer text), `done`, or `error`. EventSource only supports GET, so we read the stream by hand.
export async function askStream({ question, strategy, documentId }, { onRoute, onRetrieval, onToken, signal }) {
  const res = await fetch(`${BASE_URL}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, strategy, document_id: documentId ?? null }),
    signal,
  })
  if (!res.ok) throw new Error(await errorMessage(res))

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handle = (raw) => {
    let event = 'message'
    let data = ''
    for (const line of raw.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7)
      else if (line.startsWith('data: ')) data += line.slice(6)
    }
    const payload = data ? JSON.parse(data) : {}
    if (event === 'route') onRoute(payload.route)
    else if (event === 'retrieval') onRetrieval(payload.chunks)
    else if (event === 'token') onToken(payload.text)
    else if (event === 'error') throw new Error(payload.detail)
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop()
    events.forEach(handle)
  }
}
