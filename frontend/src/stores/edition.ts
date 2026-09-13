import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchAgentProfileOptions } from '@/api/agentProfiles'
export const useEditionStore = defineStore('edition', () => {
  const edition = ref<'product' | 'research' | null>(null)
  let pending: Promise<void> | null = null
  async function load(force = false): Promise<void> {
    if (pending) return pending
    if (edition.value && !force) return
    pending = fetchAgentProfileOptions()
      .then((value) => {
        edition.value = value.edition
      })
      .catch((error) => {
        edition.value = null
        throw error
      })
      .finally(() => {
        pending = null
      })
    return pending
  }
  return { edition, load }
})
