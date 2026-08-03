import { defineStore } from 'pinia'
import { ref } from 'vue'

import { fetchLLMConfiguration } from '@/api/qa'
import type { LLMConfiguration } from '@/types/api'

export const useLLMStore = defineStore('llm', () => {
  const configuration = ref<LLMConfiguration | null>(null)
  const selectedModel = ref('')
  const loading = ref(false)

  async function loadConfiguration(force = false): Promise<LLMConfiguration> {
    if (configuration.value && !force) {
      return configuration.value
    }
    loading.value = true
    try {
      const loaded = await fetchLLMConfiguration()
      configuration.value = loaded
      if (!loaded.available_models.includes(selectedModel.value)) {
        selectedModel.value = loaded.model
      }
      return loaded
    } finally {
      loading.value = false
    }
  }

  function selectModel(model: string): void {
    if (configuration.value?.available_models.includes(model)) {
      selectedModel.value = model
    }
  }

  return { configuration, selectedModel, loading, loadConfiguration, selectModel }
})
