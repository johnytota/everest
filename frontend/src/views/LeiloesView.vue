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
          <div class="pt-2 border-t border-slate-100 flex gap-3">
            <!-- Datas + contadores -->
            <div class="flex-1 space-y-1.5 text-xs text-slate-500">
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
            <!-- Gauge -->
            <div v-if="l.stats_total > 0" class="shrink-0 flex items-center">
              <svg viewBox="0 0 100 56" class="w-24 h-auto">
                <!-- Arco de fundo -->
                <path d="M 8.6 46.7 A 42 42 0 0 1 91.4 46.7"
                      fill="none" stroke="#e2e8f0" stroke-width="7" stroke-linecap="round"/>
                <!-- Arco preenchido -->
                <path v-if="l.stats_licitados > 0"
                      :d="gaugeArcPath(l.stats_licitados, l.stats_total)"
                      fill="none"
                      :stroke="licitacaoColor(l.stats_licitados, l.stats_total)"
                      stroke-width="7" stroke-linecap="round"/>
                <!-- Ponteiro -->
                <line x1="50" y1="54"
                      :x2="gaugePt(l.stats_licitados, l.stats_total).x"
                      :y2="gaugePt(l.stats_licitados, l.stats_total).y"
                      stroke="#334155" stroke-width="1.8" stroke-linecap="round"/>
                <!-- Ponto central -->
                <circle cx="50" cy="54" r="2.5" fill="#334155"/>
                <!-- Etiqueta esquerda (0) -->
                <text x="3" y="56" font-size="7" fill="#94a3b8" font-family="sans-serif">0</text>
                <!-- Etiqueta direita (total) -->
                <text :x="l.stats_total >= 100 ? 79 : l.stats_total >= 10 ? 84 : 89"
                      y="56" font-size="7" fill="#94a3b8" font-family="sans-serif">{{ l.stats_total }}</text>
                <!-- Valor central -->
                <text x="50" y="38" font-size="11" text-anchor="middle" font-weight="600"
                      :fill="licitacaoColor(l.stats_licitados, l.stats_total)"
                      font-family="sans-serif">{{ l.stats_licitados }}</text>
              </svg>
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

// Centro: (50, 54), raio: 42, arco de 190° a 350° (160° no sentido horário)
const CX = 50, CY = 54, R = 42, R_NEEDLE = 36
const START_DEG = 190, SPAN_DEG = 160

function gaugeAngle(licitados, total) {
  const ratio = total ? Math.min(licitados / total, 1) : 0
  return (START_DEG + ratio * SPAN_DEG) * Math.PI / 180
}

function gaugeArcPath(licitados, total) {
  const ratio = total ? Math.min(licitados / total, 1) : 0
  if (ratio === 0) return ''
  const a0 = START_DEG * Math.PI / 180
  const a1 = gaugeAngle(licitados, total)
  const x1 = CX + R * Math.cos(a0), y1 = CY + R * Math.sin(a0)
  const x2 = CX + R * Math.cos(a1), y2 = CY + R * Math.sin(a1)
  const large = ratio * SPAN_DEG >= 180 ? 1 : 0
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${R} ${R} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`
}

function gaugePt(licitados, total) {
  const a = gaugeAngle(licitados, total)
  return {
    x: (CX + R_NEEDLE * Math.cos(a)).toFixed(1),
    y: (CY + R_NEEDLE * Math.sin(a)).toFixed(1),
  }
}

function licitacaoColor(licitados, total) {
  if (!total) return '#94a3b8'
  const ratio = licitados / total
  if (ratio === 0)   return '#94a3b8' // slate-400
  if (ratio < 0.25)  return '#fb923c' // orange-400
  if (ratio < 0.5)   return '#f97316' // orange-500
  if (ratio < 0.75)  return '#ef4444' // red-500
  return '#dc2626'                    // red-600
}

function formatDate(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('pt-PT', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>
