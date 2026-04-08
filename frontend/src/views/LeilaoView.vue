<template>
  <div>

    <Button
      icon="pi pi-arrow-left"
      label="Todos os leilões"
      text
      class="mb-4 -ml-2"
      @click="$router.push('/')"
    />

    <div v-if="loading" class="flex justify-center py-20">
      <ProgressSpinner />
    </div>

    <template v-else>

      <!-- Cabeçalho -->
      <div class="flex items-start justify-between gap-4 mb-6">
        <div>
          <p v-if="leilao?.descricao" class="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-1">
            {{ leilao.descricao }}
          </p>
          <h1 class="text-2xl font-semibold text-slate-800">{{ leilao?.nome }}</h1>
          <div class="flex flex-wrap items-center gap-3 mt-2 text-sm text-slate-500">
            <span>{{ leilao?.sale_type }}</span>
            <span v-if="leilao?.data_inicio" class="flex items-center gap-1">
              <i class="pi pi-calendar text-xs" />
              Início: {{ formatDate(leilao.data_inicio) }}
            </span>
            <span v-if="leilao?.data_fim" class="flex items-center gap-1">
              <i class="pi pi-clock text-xs" />
              Fecho: {{ formatDate(leilao.data_fim) }}
            </span>
            <span v-if="leilao?.scrape_ts" class="flex items-center gap-1 text-slate-400">
              <i class="pi pi-database text-xs" />
              Introduzido: {{ formatDate(leilao.scrape_ts) }}
            </span>
          </div>
        </div>
        <Tag
          :value="leilao?.estado === 3 ? 'Aberto' : 'Encerrado'"
          :severity="leilao?.estado === 3 ? 'success' : 'secondary'"
          class="shrink-0 mt-1"
        />
      </div>

      <!-- Filtro -->
      <div class="mb-4 max-w-sm">
        <IconField>
          <InputIcon class="pi pi-search" />
          <InputText v-model="filtro" placeholder="Filtrar veículos..." class="w-full" />
        </IconField>
      </div>

      <!-- Tabela -->
      <DataTable
        :value="veiculosFiltrados"
        :rows="150"
        paginator
        stripedRows
        selectionMode="single"
        @rowSelect="abrirVeiculo"
        class="text-sm"
      >
        <Column field="numero_lote" header="Lote" sortable style="width: 70px" />
        <Column field="marca_modelo" header="Viatura" sortable />
        <Column field="matricula" header="Matrícula" sortable style="width: 110px" />
        <Column field="km" header="Km" sortable style="width: 100px" />
        <Column field="data_registo" header="Registo" style="width: 100px" />
        <Column field="combustivel" header="Combustível" style="width: 110px" />
        <Column header="Valor Atual" sortable sortField="bid_amount" style="width: 130px">
          <template #body="{ data }">
            <span
              :class="['font-semibold', novoPrecoLots.has(data.lot_id) ? 'text-green-600 animate-pulse' : 'text-slate-800']"
            >
              {{ data.bid_amount != null ? `${data.bid_amount.toLocaleString('pt-PT')} €` : '-' }}
            </span>
          </template>
        </Column>
        <Column header="Docs" style="width: 80px">
          <template #body="{ data }">
            <div class="flex gap-2">
              <a v-if="data.doc_manutencao" :href="data.doc_manutencao" target="_blank" title="Histórico manutenção">
                <i class="pi pi-wrench text-slate-400 hover:text-blue-600 transition-colors" />
              </a>
              <a v-if="data.doc_peritagem" :href="data.doc_peritagem" target="_blank" title="Relatório peritagem">
                <i class="pi pi-file text-slate-400 hover:text-blue-600 transition-colors" />
              </a>
            </div>
          </template>
        </Column>
      </DataTable>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import InputText from 'primevue/inputtext'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import ProgressSpinner from 'primevue/progressspinner'
import { useSse } from '../composables/useSse'

const route  = useRoute()
const router = useRouter()

const leilao  = ref(null)
const veiculos = ref([])
const loading = ref(true)
const filtro  = ref('')
const novoPrecoLots = ref(new Set())

onMounted(async () => {
  const [resL, resV] = await Promise.all([
    fetch(`/api/leiloes/${route.params.id}`),
    fetch(`/api/leiloes/${route.params.id}/veiculos`),
  ])
  leilao.value  = await resL.json()
  veiculos.value = await resV.json()
  loading.value = false
})

useSse((evento) => {
  if (evento.sale_id !== route.params.id) return
  const v = veiculos.value.find(v => v.lot_id === evento.lot_id)
  if (v) {
    v.bid_amount = evento.valor
    novoPrecoLots.value.add(evento.lot_id)
    setTimeout(() => novoPrecoLots.value.delete(evento.lot_id), 3000)
  }
})

const veiculosFiltrados = computed(() => {
  if (!filtro.value) return veiculos.value
  const q = filtro.value.toLowerCase()
  return veiculos.value.filter(v =>
    v.marca_modelo?.toLowerCase().includes(q) ||
    v.matricula?.toLowerCase().includes(q) ||
    v.numero_lote?.toString().includes(q)
  )
})

function abrirVeiculo({ data }) {
  router.push(`/veiculos/${data.lot_id}`)
}

function formatDate(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('pt-PT', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>
