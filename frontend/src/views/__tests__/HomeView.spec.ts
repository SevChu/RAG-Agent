import { describe, expect, it } from 'vitest'
import { createApp } from 'vue'

import HomeView from '../HomeView.vue'

describe('HomeView', () => {
  it('shows the day-one foundation status', () => {
    const container = document.createElement('div')
    const app = createApp(HomeView)
    app.component('ElTag', {
      template: '<span><slot /></span>',
    })
    app.mount(container)

    expect(container.textContent).toContain('工程骨架已经就绪')

    app.unmount()
  })
})
