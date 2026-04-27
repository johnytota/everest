<template>
  <div>

    <div class="mb-6">
      <h1 class="text-2xl font-semibold text-slate-800">Resultados da pesquisa</h1>
      <p class="text-sm text-slate-400 mt-1">
        {{ loading ? 'A pesquisar...' : `${veiculos.length} resultado${veiculos.length !== 1 ? 's' : ''} para "${query}"` }}
      </p>
    </div>

    <div v-if="loading" class="flex justify-center py-20">
      <ProgressSpinner />
    </div>

    <div v-else-if="veiculos.length === 0" class="text-slate-400 text-center py-20 text-sm">
      Nenhum veículo encontrado para "{{ query }}".
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      <div
        v-for="v in veiculos"
        :key="v.veiculo_id"
        class="bg-white rounded-xl border border-slate-200 overflow-hidden cursor-pointer hover:shadow-md transition-shadow"
        @click="$router.push(`/veiculos/${v.veiculo_id}`)"
      >
        <!-- Foto -->
        <div class="h-44 bg-slate-100 flex items-center justify-center overflow-hidden">
          <img
            v-if="v.imagem_url"
            :src="v.imagem_url"
            :alt="v.marca_modelo"
            referrerpolicy="no-referrer"
            class="w-full h-full object-cover"
          />
          <i v-else class="pi pi-car text-4xl text-slate-300" />
        </div>

        <!-- Info -->
        <div class="p-4">
          <p class="font-semibold text-slate-800 text-sm leading-snug">{{ v.marca_modelo }}</p>
          <div class="flex items-center gap-2 mt-0.5 text-xs flex-wrap">
            <span v-if="v.matricula" class="text-blue-500">{{ v.matricula }}</span>
            <span v-if="v.ano_construcao && v.ano_construcao !== '0'" class="text-slate-400">{{ v.ano_construcao }}</span>
            <span v-if="v.km" class="text-slate-400">{{ Number(v.km).toLocaleString('pt-PT') }} km</span>
          </div>

          <div class="mt-3 pt-3 border-t border-slate-100 grid grid-cols-3 gap-2 text-xs text-center">
            <div>
              <p class="text-slate-400">Leilões</p>
              <p class="font-semibold text-slate-700">{{ v.num_leiloes }}</p>
            </div>
            <div>
              <p class="text-slate-400">Licitações</p>
              <p class="font-semibold text-slate-700">{{ v.num_bids }}</p>
            </div>
            <div>
              <p class="text-slate-400">Último leilão</p>
              <p v-if="v.preco_inicial != null" class="font-semibold text-slate-700 leading-tight">
                {{ v.preco_inicial.toLocaleString('pt-PT') }} →
                <span :class="v.preco_final > v.preco_inicial ? 'text-green-600' : 'text-slate-700'">
                  {{ v.preco_final?.toLocaleString('pt-PT') }} €
                </span>
              </p>
              <p v-else class="text-slate-300">—</p>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import ProgressSpinner from 'primevue/progressspinner'

const route    = useRoute()
const veiculos = ref([])
const loading  = ref(false)
const query    = ref('')

async function pesquisar(q) {
  query.value    = q
  veiculos.value = []
  if (!q) return
  loading.value = true
  const res = await fetch(`/api/pesquisa/sugestoes?q=${encodeURIComponent(q)}`)
  veiculos.value = await res.json()
  loading.value = false
}

onMounted(() => pesquisar(route.query.q || ''))
watch(() => route.query.q, (q) => pesquisar(q || ''))
</script>
