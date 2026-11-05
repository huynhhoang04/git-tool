export const EXPECTED_API_VERSION = 4

const tokenFromUrl = new URLSearchParams(window.location.search).get('token')
if (tokenFromUrl) sessionStorage.setItem('keyRouterToolToken', tokenFromUrl)
export const TOOL_TOKEN = tokenFromUrl || sessionStorage.getItem('keyRouterToolToken') || ''

export async function api(path, options = {}) {
  const { method = 'GET', body } = options
  const res = await fetch(path, {
    method,
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(TOOL_TOKEN ? { 'X-Tool-Token': TOOL_TOKEN } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = data.detail
    throw new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `Request failed (${res.status})`)
  }
  return data
}
