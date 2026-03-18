<script setup lang="ts">
import { Chat } from '@ai-sdk/vue'
import { TextStreamChatTransport } from 'ai'
import type { UIMessage } from 'ai'

const input = ref('')
const chatStarted = ref(false)
const chatTitle = useChatTitle()
const chatActive = useChatActive()

const chat = new Chat({
  transport: new TextStreamChatTransport({
    api: 'http://127.0.0.1:8000/api/chat/stream',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
})

async function onSubmit() {
  if (!input.value.trim()) return
  if (!chatStarted.value) {
    chatTitle.value = input.value.slice(0, 40) + (input.value.length > 40 ? '...' : '')
    chatActive.value = true
  }
  chatStarted.value = true
  chat.sendMessage({ text: input.value })
  input.value = ''
}

function sendQuickChat(label: string) {
  input.value = label
  onSubmit()
}

const quickChats = [
  { label: 'Konut kredisi LTV oranı nedir?', icon: 'i-lucide-building' },
  { label: 'Son kredi kartı düzenlemeleri neler?', icon: 'i-lucide-credit-card' },
  { label: 'Dijital bankacılık faaliyet esasları', icon: 'i-lucide-smartphone' },
  { label: 'Sermaye yeterliliği oranı nasıl hesaplanır?', icon: 'i-lucide-calculator' },
  { label: 'BDDK denetim süreci nasıl işler?', icon: 'i-lucide-shield-check' },
  { label: 'Banka kuruluş şartları nelerdir?', icon: 'i-lucide-landmark' }
]

const copied = ref(false)
function copy(e: MouseEvent, message: UIMessage) {
  const text = message.parts?.filter(p => p.type === 'text').map(p => (p as any).text).join('\n') || ''
  navigator.clipboard.writeText(text)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}
</script>

<template>
  <UDashboardPanel
    id="home"
    class="min-h-0"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <DashboardNavbar />
    </template>

    <template #body>
      <div class="flex flex-1">
        <UContainer v-if="!chatStarted" class="flex-1 flex flex-col justify-center gap-4 sm:gap-6 py-8">
          <h1 class="text-3xl sm:text-4xl text-highlighted font-bold">
            Size nasıl yardımcı olabilirim?
          </h1>

          <UChatPrompt
            v-model="input"
            placeholder="Regülasyonlar hakkında bir soru sorun..."
            :status="'ready'"
            class="[view-transition-name:chat-prompt]"
            variant="subtle"
            :ui="{ base: 'px-1.5' }"
            @submit="onSubmit"
          >
            <template #footer>
              <div />
              <UChatPromptSubmit color="neutral" size="sm" />
            </template>
          </UChatPrompt>

          <div class="flex flex-wrap gap-2">
            <UButton
              v-for="qc in quickChats"
              :key="qc.label"
              :icon="qc.icon"
              :label="qc.label"
              size="sm"
              color="neutral"
              variant="outline"
              class="rounded-full"
              @click="sendQuickChat(qc.label)"
            />
          </div>
        </UContainer>

        <UContainer v-else class="flex-1 flex flex-col gap-4 sm:gap-6">
          <UChatMessages
            should-auto-scroll
            :messages="chat.messages"
            :status="chat.status"
            :assistant="chat.status !== 'streaming' ? { actions: [{ label: 'Kopyala', icon: copied ? 'i-lucide-copy-check' : 'i-lucide-copy', onClick: copy }] } : { actions: [] }"
            :spacing-offset="160"
            class="pb-4 sm:pb-6 pt-4"
          >
            <template #content="{ message }">
              <template v-for="(part, index) in message.parts" :key="`${message.id}-${part.type}-${index}`">
                <MDCCached
                  v-if="part.type === 'text' && message.role === 'assistant'"
                  :value="(part as any).text"
                  :cache-key="`${message.id}-${index}`"
                  :parser-options="{ highlight: false }"
                  class="*:first:mt-0 *:last:mb-0"
                />
                <p v-else-if="part.type === 'text' && message.role === 'user'" class="whitespace-pre-wrap">
                  {{ (part as any).text }}
                </p>
              </template>
            </template>
          </UChatMessages>

          <UChatPrompt
            v-model="input"
            placeholder="Regülasyonlar hakkında bir soru sorun..."
            :error="chat.error"
            variant="subtle"
            class="sticky bottom-0 [view-transition-name:chat-prompt] rounded-b-none z-10"
            :ui="{ base: 'px-1.5' }"
            @submit="onSubmit"
          >
            <template #footer>
              <div />
              <UChatPromptSubmit
                :status="chat.status"
                color="neutral"
                size="sm"
                @stop="chat.stop()"
                @reload="chat.regenerate()"
              />
            </template>
          </UChatPrompt>
        </UContainer>
      </div>
    </template>
  </UDashboardPanel>
</template>
