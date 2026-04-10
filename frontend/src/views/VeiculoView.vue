<template>
  <div class="max-w-5xl">

    <Button
      icon="pi pi-arrow-left"
      label="Voltar ao leilão"
      text
      class="mb-4 -ml-2"
      @click="$router.back()"
    />

    <div v-if="loading" class="flex justify-center py-20">
      <ProgressSpinner />
    </div>

    <template v-else-if="veiculo">

      <!-- Cabeçalho -->
      <div class="flex items-start justify-between gap-6 mb-6">
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">{{ veiculo.marca_modelo }}</h1>
          <p class="text-slate-500 mt-1 text-sm">{{ veiculo.versao }} · {{ veiculo.matricula }} · #{{ veiculo.lot_id }}</p>
          <a
            :href="`https://carmarket.ayvens.com/pt-pt/sales/${veiculo.sale_id}/#vehicle-${veiculo.lot_id}`"
            target="_blank"
            class="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mt-2"
          >
            <i class="pi pi-external-link text-xs" />
            Ver no Ayvens Carmarket
          </a>
        </div>
        <div v-if="leilaoAberto" class="text-right shrink-0">
          <div class="text-xs text-slate-400 mb-3">
            Base de licitação
            <span class="ml-1 font-semibold text-slate-600 text-sm">
              {{ baseLicitacao != null ? `${baseLicitacao.toLocaleString('pt-PT')} €` : '-' }}
            </span>
          </div>
          <div :class="['text-3xl font-bold', precoAtualizado ? 'text-green-600' : 'text-slate-800']">
            {{ ultimoPreco != null ? `${ultimoPreco.toLocaleString('pt-PT')} €` : '-' }}
          </div>
          <p class="text-xs text-slate-400 mt-0.5 mb-2">Oferta atual</p>
          <div class="flex justify-end gap-2">
            <Tag v-if="veiculo.is_sold" value="Vendido" severity="danger" />
            <Tag v-if="veiculo.is_withdrawn" value="Retirado" severity="warn" />
          </div>
        </div>
      </div>

      <!-- Foto -->
      <div class="mb-6 rounded-xl overflow-hidden bg-slate-100 flex items-center justify-center h-72">
        <img
          v-if="veiculo.imagem_url"
          :src="veiculo.imagem_url"
          :alt="veiculo.marca_modelo"
          class="object-cover"
        />
        <div v-else class="flex flex-col items-center gap-2 text-slate-400">
          <i class="pi pi-car text-5xl" />
          <span class="text-sm">Sem fotografia disponível</span>
        </div>
      </div>

      <!-- Detalhes + Histórico leilão atual -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">

        <Card>
          <template #title>Detalhes</template>
          <template #content>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="(val, label) in detalhesCarro" :key="label" class="border-b border-slate-100 last:border-0">
                  <td class="py-2 text-slate-500 w-1/2">{{ label }}</td>
                  <td class="py-2 font-medium text-slate-800">{{ val || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </Card>

        <Card>
          <template #title>
            <router-link v-if="leilaoAberto" :to="`/leiloes/${veiculo.sale_id}`" class="text-blue-600 hover:underline">
              Histórico de Preços — Leilão Atual
            </router-link>
            <span v-else class="text-slate-500">Sem leilão ativo</span>
          </template>
          <template #content>
            <div v-if="!leilaoAberto" class="text-slate-400 text-sm py-2">
              Não existem leilões ativos para esta viatura.
            </div>
            <div v-else>
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div>
                  <p class="text-xs text-slate-700 uppercase font-medium tracking-wide mb-2">Polling</p>
                  <div v-if="historico.length === 0" class="text-slate-400 text-sm">Sem registos.</div>
                  <div v-else class="space-y-0 max-h-64 overflow-y-auto pr-2">
                    <div
                      v-for="(h, i) in historicoInvertido"
                      :key="i"
                      :class="['flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0 text-sm', i === historicoInvertido.length - 1 ? 'opacity-40' : '']"
                    >
                      <span class="text-slate-400 text-xs">{{ formatDate(h.timestamp) }}</span>
                      <span class="font-semibold" :class="i === 0 && i !== historicoInvertido.length - 1 ? 'text-green-600' : 'text-slate-700'">
                        {{ h.valor.toLocaleString('pt-PT') }} €
                      </span>
                    </div>
                  </div>
                </div>
                <div>
                  <p class="text-xs text-slate-700 uppercase font-medium tracking-wide mb-2">
                    <i class="pi pi-bolt text-yellow-500 text-xs mr-1" />WebSocket
                  </p>
                  <div v-if="wsBids.length === 0" class="text-slate-400 text-sm">Sem registos.</div>
                  <div v-else class="space-y-0 max-h-64 overflow-y-auto pr-2">
                    <div
                      v-for="(b, i) in [...wsBids].reverse()"
                      :key="i"
                      class="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0 text-sm"
                    >
                      <span class="text-slate-400 text-xs">{{ formatDate(b.timestamp_ayvens) }}</span>
                      <span class="font-semibold" :class="i === 0 ? 'text-yellow-600' : 'text-slate-700'">
                        {{ b.valor.toLocaleString('pt-PT') }} €
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </Card>

      </div>

      <!-- Leilões anteriores -->
      <div v-if="leiloesAnteriores.length > 0" class="mb-6">
        <h2 class="text-lg font-semibold text-slate-700 mb-3">Leilões Anteriores</h2>
        <div class="space-y-4">
          <Card v-for="r in leiloesAnteriores" :key="r.veiculo.lot_id">
            <template #title>
              <div class="flex items-start justify-between gap-4">
                <div>
                  <router-link :to="`/leiloes/${r.veiculo.sale_id}`" class="text-blue-600 hover:underline text-base font-medium">
                    {{ r.leilao?.nome || r.veiculo.sale_id }}
                  </router-link>
                  <p v-if="r.leilao?.descricao" class="text-xs font-semibold uppercase tracking-wide mb-1">
                    {{ r.leilao.descricao }}
                  </p>
                </div>
                <div class="flex items-center gap-3 shrink-0">
                  <span v-if="r.leilao?.data_inicio" class="text-xs text-slate-400">
                    {{ formatDate(r.leilao.data_inicio) }} → {{ formatDate(r.leilao.data_fim) }}
                  </span>
                  <Tag
                    :value="r.leilao?.estado === 3 ? 'Aberto' : 'Encerrado'"
                    :severity="r.leilao?.estado === 3 ? 'success' : 'secondary'"
                  />
                </div>
              </div>
            </template>
            <template #content>
              <div class="flex items-center gap-6 mb-4 text-sm">
                <span class="text-slate-400">
                  Lote <strong class="text-slate-700">#{{ r.veiculo.numero_lote }}</strong>
                </span>
                <span class="text-slate-400">
                  Valor final
                  <strong class="text-slate-700">
                    {{ r.veiculo.bid_amount != null ? `${r.veiculo.bid_amount.toLocaleString('pt-PT')} €` : '-' }}
                  </strong>
                </span>
              </div>
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div>
                  <p class="text-xs text-slate-700 uppercase font-medium tracking-wide mb-2">Histórico de Preços (Polling)</p>
                  <div v-if="r.historico.length === 0" class="text-slate-400 text-sm">Sem registos.</div>
                  <div v-else class="space-y-0 max-h-48 overflow-y-auto pr-2">
                    <div
                      v-for="(h, i) in [...r.historico].reverse()"
                      :key="i"
                      :class="['flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0 text-sm', i === r.historico.length - 1 ? 'opacity-40' : '']"
                    >
                      <span class="text-slate-400 text-xs">{{ formatDate(h.timestamp) }}</span>
                      <span class="font-semibold" :class="i === 0 && i !== r.historico.length - 1 ? 'text-green-600' : 'text-slate-600'">
                        {{ h.valor.toLocaleString('pt-PT') }} €
                      </span>
                    </div>
                  </div>
                </div>
                <div>
                  <p class="text-xs text-slate-700 uppercase font-medium tracking-wide mb-2">Histórico de Preços (WebSocket)</p>
                  <div v-if="r.wsBids.length === 0" class="text-slate-400 text-sm">Sem registos.</div>
                  <div v-else class="space-y-0 max-h-48 overflow-y-auto pr-2">
                    <div
                      v-for="(b, i) in [...r.wsBids].reverse()"
                      :key="i"
                      class="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0 text-sm"
                    >
                      <span class="text-slate-400 text-xs">{{ formatDate(b.timestamp_ayvens) }}</span>
                      <span class="font-semibold" :class="i === 0 ? 'text-yellow-600' : 'text-slate-600'">
                        {{ b.valor.toLocaleString('pt-PT') }} €
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </Card>
        </div>
      </div>

      <!-- Documentos -->
      <div v-if="veiculo.doc_manutencao || veiculo.doc_peritagem" class="flex gap-3">
        <a v-if="veiculo.doc_manutencao" :href="veiculo.doc_manutencao" target="_blank">
          <Button icon="pi pi-wrench" label="Histórico de Manutenção" outlined size="small" />
        </a>
        <a v-if="veiculo.doc_peritagem" :href="veiculo.doc_peritagem" target="_blank">
          <Button icon="pi pi-file" label="Relatório de Peritagem" outlined size="small" />
        </a>
      </div>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import Card from 'primevue/card'
import Tag from 'primevue/tag'
import Button from 'primevue/button'
import ProgressSpinner from 'primevue/progressspinner'
import { useSse } from '../composables/useSse'

const route = useRoute()

const veiculo           = ref(null)
const leilaoAtual       = ref(null)
const historico         = ref([])
const wsBids            = ref([])
const leiloesAnteriores = ref([])
const loading           = ref(true)
const precoAtualizado   = ref(false)

const leilaoAberto = computed(() => leilaoAtual.value?.estado === 3)

onMounted(async () => {
  const [resV, resH] = await Promise.all([
    fetch(`/api/veiculos/${route.params.id}`),
    fetch(`/api/veiculos/${route.params.id}/historico`),
  ])
  veiculo.value   = await resV.json()
  historico.value = await resH.json()

  const resL = await fetch(`/api/leiloes/${veiculo.value.sale_id}`)
  leilaoAtual.value = await resL.json()

  loading.value = false

  const [resWs, resPesquisa] = await Promise.all([
    fetch(`/api/veiculos/${route.params.id}/ws_bids`),
    veiculo.value?.matricula
      ? fetch(`/api/pesquisa?matricula=${encodeURIComponent(veiculo.value.matricula)}`)
      : Promise.resolve({ json: () => [] }),
  ])
  wsBids.value = await resWs.json()
  const todos = await resPesquisa.json()
  // Se o leilão está encerrado, incluir a própria viatura nos anteriores
  const anteriores = todos.filter(r =>
    r.veiculo.lot_id !== route.params.id || leilaoAtual.value?.estado !== 3
  )
  await Promise.all(anteriores.map(async r => {
    if (r.veiculo.lot_id === route.params.id) {
      r.wsBids = wsBids.value
    } else {
      const res = await fetch(`/api/veiculos/${r.veiculo.lot_id}/ws_bids`)
      r.wsBids = res.ok ? await res.json() : []
    }
  }))
  leiloesAnteriores.value = anteriores
})

useSse((evento) => {
  if (evento.lot_id !== route.params.id) return
  historico.value.push({ valor: evento.valor, timestamp: evento.timestamp })
  if (evento.offers_count != null) veiculo.value.offers_count = evento.offers_count
  if (evento.is_sold != null)      veiculo.value.is_sold      = evento.is_sold
  if (evento.is_withdrawn != null) veiculo.value.is_withdrawn  = evento.is_withdrawn
  precoAtualizado.value = true
  setTimeout(() => { precoAtualizado.value = false }, 3000)
})

const historicoInvertido = computed(() => [...historico.value].reverse())
const ultimoPreco   = computed(() => historico.value.length ? historico.value[historico.value.length - 1].valor : null)
const baseLicitacao = computed(() => {
  const base = historico.value.find(h => !h.has_offer)
  return base ? base.valor : (historico.value.length ? historico.value[0].valor : null)
})

const detalhesCarro = computed(() => {
  if (!veiculo.value) return {}
  const v = veiculo.value
  return {
    'Km':              v.km,
    'Data de Registo': v.data_registo,
    'Ano Construção':  v.ano_construcao,
    'Combustível':     v.combustivel,
    'Caixa':           v.caixa,
    'Carroçaria':      v.carrocaria,
    'Portas':          v.portas,
    'Lugares':         v.lugares,
    'Categoria':       v.categoria,
    'Cor Exterior':    v.cor_exterior,
    'Potência (cv)':   v.potencia_cv,
    'Cilindrada':      v.cilindrada,
    'Chassis':         v.chassis,
    'Eurotax Venda':   v.eurotax_venda,
    'Eurotax Compra':  v.eurotax_compra,
    'Localização':     v.localizacao,
    'Fornecedor':      v.fornecedor,
  }
})

function formatDate(ts) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('pt-PT', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>
