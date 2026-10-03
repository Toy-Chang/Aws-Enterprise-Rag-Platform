import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library unmounts what each test rendered, so no test sees another test's DOM.
afterEach(() => {
  cleanup()
})
