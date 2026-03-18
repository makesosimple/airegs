<script setup lang="ts">
const open = ref(false)
const chatTitle = useChatTitle()
const chatActive = useChatActive()

function newChat() {
  chatActive.value = false
  chatTitle.value = ''
  open.value = false
  navigateTo('/')
  // Force page reload to reset chat state
  setTimeout(() => window.location.reload(), 50)
}
</script>

<template>
  <UDashboardGroup unit="rem">
    <UDashboardSidebar
      id="default"
      v-model:open="open"
      :min-size="12"
      collapsible
      resizable
      class="border-r-0 py-4"
    >
      <template #header="{ collapsed }">
        <NuxtLink to="/" class="flex items-end gap-1.5">
          <UIcon name="i-lucide-shield-check" class="h-7 w-7 text-primary shrink-0" />
          <span v-if="!collapsed" class="text-lg font-bold text-highlighted">Regülasyon</span>
        </NuxtLink>
      </template>

      <template #default="{ collapsed }">
        <div class="flex flex-col gap-1.5">
          <UButton
            v-bind="collapsed ? { icon: 'i-lucide-plus' } : { label: 'Yeni Sohbet' }"
            variant="soft"
            block
            @click="newChat"
          />

          <UButton
            v-if="chatActive && !collapsed"
            :label="chatTitle || 'Aktif Sohbet'"
            icon="i-lucide-message-circle"
            variant="ghost"
            block
            class="justify-start text-left truncate"
            color="primary"
          />
        </div>
      </template>

      <template #footer="{ collapsed }">
        <NuxtLink to="/admin">
          <UButton
            :label="collapsed ? '' : 'Doküman Yönetimi'"
            icon="i-lucide-settings"
            color="neutral"
            variant="ghost"
            class="w-full"
          />
        </NuxtLink>
      </template>
    </UDashboardSidebar>

    <div class="flex-1 flex m-4 lg:ml-0 rounded-lg ring ring-default bg-default/75 shadow min-w-0">
      <slot />
    </div>
  </UDashboardGroup>
</template>
