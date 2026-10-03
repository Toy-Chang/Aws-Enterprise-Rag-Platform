/**
 * The states every screen has: loading, failed, empty.
 *
 * The failure state shows what the backend actually said — its code, its message, its field
 * details and the request id — because that is what makes a report actionable. It is the
 * reason the API has one error envelope and why the client keeps all of it.
 */

import type { ReactNode } from 'react'

import { ApiError, validationMessages } from '../api/client'

export function Loading({ label = 'Loading…' }: { label?: string }): ReactNode {
  return (
    <p className="state state--loading" role="status">
      {label}
    </p>
  )
}

export function EmptyState({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}): ReactNode {
  return (
    <div className="state state--empty">
      <p className="state__title">{title}</p>
      {children ? <div className="state__body">{children}</div> : null}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: ApiError
  onRetry?: (() => void) | undefined
}): ReactNode {
  const fields = validationMessages(error)
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">
        {error.isTransportFailure ? 'The API could not be reached' : error.message}
      </p>
      <dl className="state__details">
        <dt>Code</dt>
        <dd>{error.code}</dd>
        {error.status > 0 ? (
          <>
            <dt>Status</dt>
            <dd>{error.status}</dd>
          </>
        ) : null}
        {error.isTransportFailure ? (
          <>
            <dt>Detail</dt>
            <dd>{String(error.details)}</dd>
          </>
        ) : null}
        {error.requestId ? (
          <>
            <dt>Request id</dt>
            <dd className="mono">{error.requestId}</dd>
          </>
        ) : null}
      </dl>
      {fields.length > 0 ? (
        <ul className="state__fields">
          {fields.map((field) => (
            <li key={field}>{field}</li>
          ))}
        </ul>
      ) : null}
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}
