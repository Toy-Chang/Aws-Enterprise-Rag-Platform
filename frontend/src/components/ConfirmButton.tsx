/**
 * A destructive action that asks once, in place.
 *
 * `window.confirm` blocks the event loop, cannot be styled, is untestable in jsdom, and on
 * some browsers can be suppressed entirely — which would make a delete button that deletes
 * without asking. Arming a second click is the same protection without any of that.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'

export function ConfirmButton({
  label,
  confirmLabel = 'Confirm',
  onConfirm,
  disabled = false,
}: {
  label: string
  confirmLabel?: string
  onConfirm: () => void | Promise<void>
  disabled?: boolean
}): ReactNode {
  const [armed, setArmed] = useState(false)

  if (!armed) {
    return (
      <button
        type="button"
        className="button button--small button--danger"
        disabled={disabled}
        onClick={() => {
          setArmed(true)
        }}
      >
        {label}
      </button>
    )
  }

  return (
    <span className="row">
      <button
        type="button"
        className="button button--small button--danger"
        onClick={() => {
          setArmed(false)
          void onConfirm()
        }}
      >
        {confirmLabel}
      </button>
      <button
        type="button"
        className="button button--small"
        onClick={() => {
          setArmed(false)
        }}
      >
        Cancel
      </button>
    </span>
  )
}
