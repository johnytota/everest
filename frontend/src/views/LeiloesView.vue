<template>
  <div>

    <div class="mb-6">
      <h1 class="text-2xl font-semibold text-slate-800">Leilões Portugal</h1>
      <p class="text-sm text-slate-400 mt-1">Ayvens Carmarket — leilões ativos</p>
    </div>

    <div v-if="loading" class="flex justify-center py-20">
      <ProgressSpinner />
    </div>

    <div v-else-if="leiloes.length === 0" class="text-slate-400 text-center py-20 text-sm">
      Nenhum leilão encontrado.
    </div>
 
    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <Card
        v-for="l in leiloesOrdenados"
        :key="l.sale_id"
        class="cursor-pointer hover:shadow-md transition-shadow"
        @click="$router.push(`/leiloes/${l.sale_id}`)"
      >
        <template #title>
          <div class="flex items-start justify-between gap-2 mb-1">
            <div class="flex-1 min-w-0">
              <span class="text-sm font-semibold text-blue-600 leading-snug">{{ l.nome }}</span>
              <p v-if="l.descricao" class="text-xs font-semibold text-slate-800 uppercase tracking-wide mb-1">
                {{ l.descricao }}
              </p>
              
            </div>
            <Tag
              :value="l.estado === 3 ? 'Aberto' : 'Encerrado'"
              :severity="l.estado === 3 ? 'success' : 'secondary'"
              class="shrink-0"
            />
          </div>
        </template>
        <template #content>
          <div class="space-y-1.5 text-xs text-slate-500 pt-2 border-t border-slate-100">
            <div class="flex items-center gap-1.5">
              <i class="pi pi-car text-xs" />
              <span>{{ l.num_veiculos }} veículos</span>
            </div>
            <div v-if="l.data_inicio" class="flex items-center gap-1.5">
              <i class="pi pi-calendar text-xs" />
              <span>Início: {{ formatDate(l.data_inicio) }}</span>
            </div>
            <div v-if="l.data_fim" class="flex items-center gap-1.5">
              <i class="pi pi-clock text-xs" />
              <span>Fecho: {{ formatDate(l.data_fim) }}</span>
            </div>
            <div v-if="l.scrape_ts" class="flex items-center gap-1.5 text-slate-400">
              <i class="pi pi-database text-xs" />
              <span>Introduzido: {{ formatDate(l.scrape_ts) }}</span>
            </div>
          </div>
        </template>
      </Card>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import Card from 'primevue/card'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'

const leiloes = ref([])
const loading = ref(true)

const leiloesOrdenados = computed(() => [...leiloes.value].sort((a, b) => {
  // Leilões abertos primeiro
  if (a.estado === 3 && b.estado !== 3) return -1
  if (a.estado !== 3 && b.estado === 3) return 1
  // Dentro do mesmo estado, mais recente primeiro
  return new Date(b.data_inicio ?? 0) - new Date(a.data_inicio ?? 0)
}))

onMounted(async () => {
  const res = await fetch('/api/leiloes')
  leiloes.value = await res.json()
  loading.value = false
})

function formatDate(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('pt-PT', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>
