<script setup lang="ts">
import { ref } from 'vue'

const message = ref('')
</script>

<template>
  <section class="page-view conversation-page">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> QUICK CHAT</div>
        <h1>快速对话</h1>
        <p>适合一次性的临时问题，不关联课程资料，也不会写入课程长期上下文。</p>
      </div>
      <span class="context-pill temporary-pill">临时上下文</span>
    </header>

    <div class="conversation-stage">
      <div class="conversation-hero">
        <span class="conversation-symbol" aria-hidden="true">⌁</span>
        <span class="soft-label">LIGHTWEIGHT CONVERSATION</span>
        <h2>有什么临时问题？</h2>
        <p>快速对话能力将在后续 RAG 问答阶段接入；当前先完成入口和上下文边界设计。</p>
      </div>
      <div class="composer-shell">
        <textarea
          v-model="message"
          aria-label="快速对话消息"
          placeholder="输入一个临时问题……"
          disabled
        />
        <button type="button" disabled aria-label="发送消息">↑</button>
      </div>
      <p class="availability-note">计划日 4 仅建立页面结构，不会调用模型或保存虚假对话。</p>
    </div>
  </section>
</template>

<style scoped>
.conversation-page {
  min-height: calc(100vh - 104px);
}

.conversation-stage {
  display: grid;
  min-height: 540px;
  padding: 34px;
  background:
    radial-gradient(circle at 50% 35%, rgb(86 197 255 / 12%), transparent 28%),
    rgb(255 255 255 / 68%);
  border: 1px solid var(--line);
  border-radius: 26px;
  box-shadow: var(--shadow-card);
  place-items: center;
  align-content: center;
}

.conversation-hero {
  display: grid;
  max-width: 560px;
  text-align: center;
  place-items: center;
}

.conversation-symbol {
  display: grid;
  width: 64px;
  height: 64px;
  margin-bottom: 18px;
  font-size: 28px;
  color: #fff;
  background: linear-gradient(145deg, var(--primary), var(--violet));
  border-radius: 22px;
  box-shadow: 0 16px 36px rgb(66 135 255 / 22%);
  place-items: center;
}

.conversation-hero h2 {
  margin: 13px 0 8px;
  font-size: 24px;
  color: var(--ink-strong);
}

.conversation-hero p {
  margin: 0;
  line-height: 1.8;
  color: var(--ink-muted);
}

.composer-shell {
  display: flex;
  width: min(680px, 100%);
  padding: 10px;
  align-items: flex-end;
  gap: 10px;
  margin-top: 36px;
  background: rgb(255 255 255 / 84%);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: 0 16px 38px rgb(71 113 168 / 10%);
}

.composer-shell textarea {
  min-height: 58px;
  padding: 10px;
  flex: 1;
  resize: none;
  color: var(--ink);
  background: transparent;
  border: 0;
  outline: none;
}

.composer-shell button {
  width: 40px;
  height: 40px;
  color: #fff;
  background: var(--primary);
  border: 0;
  border-radius: 13px;
  opacity: 0.45;
}

.availability-note {
  margin: 12px 0 0;
  font-size: 11px;
  color: var(--ink-faint);
}

.temporary-pill {
  color: #6a58c9;
  background: var(--violet-soft);
}
</style>
