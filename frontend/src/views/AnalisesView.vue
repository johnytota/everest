<template>
  <div>

    <div class="mb-6">
      <h1 class="text-2xl font-semibold text-slate-800">Análises</h1>
      <p class="text-sm text-slate-400 mt-1">Viaturas em múltiplos leilões e tendências de preço</p>
    </div>

    <div v-if="loading" class="flex justify-center py-20">
      <ProgressSpinner />
    </div>

    <template v-else>

      <!-- Preço descendente -->
      <div v-if="precoDescendente.length > 0" class="mb-8">
        <div class="flex items-center gap-3 mb-3">
          <h2 class="text-base font-semibold text-slate-700">Preço a descer</h2>
          <span class="text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
            {{ precoDescendente.length }} viaturas
          </span>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-2">
          <div
            v-for="v in precoDescendenteVisiveis"
            :key="v.veiculo_id"
            class="bg-white rounded-lg border border-slate-200 overflow-hidden cursor-pointer hover:shadow-md transition-shadow"
            @click="$router.push(`/veiculos/${v.veiculo_id}`)"
          >
            <div class="h-24 bg-slate-100 flex items-center justify-center overflow-hidden relative">
              <img
                v-if="v.imagem_url"
                :src="v.imagem_url"
                :alt="v.marca_modelo"
                referrerpolicy="no-referrer"
                class="w-full h-full object-cover"
              />
              <i v-else class="pi pi-car text-2xl text-slate-300" />
              <span class="absolute top-1 right-1 bg-red-500 text-white font-semibold px-1.5 py-0.5 rounded-full" style="font-size:0.6rem">
                -{{ v.descida.toLocaleString('pt-PT') }} €
              </span>
              <span v-if="v.leilao_ativo" class="absolute top-1 left-1 bg-green-500 text-white font-semibold px-1.5 py-0.5 rounded-full" style="font-size:0.6rem">
                Ativo
              </span>
            </div>
            <div class="p-1.5">
              <p class="font-semibold text-slate-800 leading-snug truncate" style="font-size:0.65rem">{{ v.marca_modelo }}</p>
              <p v-if="v.matricula" class="text-blue-500 truncate" style="font-size:0.6rem">{{ v.matricula }}</p>
              <div class="flex items-center gap-0.5 flex-wrap mt-0.5">
                <span v-for="(p, i) in v.precos" :key="i" class="flex items-center gap-0.5" style="font-size:0.6rem">
                  <span :class="i === v.precos.length - 1 ? 'font-semibold text-red-500' : 'text-slate-400'">{{ p.toLocaleString('pt-PT') }}€</span>
                  <i v-if="i < v.precos.length - 1" class="pi pi-arrow-right text-slate-300" style="font-size:0.5rem" />
                </span>
              </div>
            </div>
          </div>
        </div>

        <button
          v-if="precoDescendente.length > PREVIEW"
          class="mt-2 text-xs text-blue-600 hover:underline"
          @click="precoExpandido = !precoExpandido"
        >
          {{ precoExpandido ? 'Recolher' : `Ver todos (${precoDescendente.length})` }}
        </button>
      </div>

      <!-- Multi-leilões sem licitações -->
      <SecaoLeiloes
        v-for="s in secoes"
        :key="s.key"
        :titulo="s.titulo"
        :items="s.items"
        class="mb-8"
      />

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import ProgressSpinner from 'primevue/progressspinner'
import SecaoLeiloes from '../components/SecaoLeiloes.vue'

const dados            = ref({})
const precoDescendente = ref([])
const loading          = ref(true)
const precoExpandido   = ref(false)
const PREVIEW          = 5

onMounted(async () => {
  const [resM, resP] = await Promise.all([
    fetch('/api/analises/multi-leiloes'),
    fetch('/api/analises/preco-descendente'),
  ])
  dados.value            = await resM.json()
  precoDescendente.value = await resP.json()
  loading.value          = false
})

const secoes = computed(() => [
  { key: 'segundo',     titulo: '2º leilão',  items: dados.value.segundo      || [] },
  { key: 'terceiro',    titulo: '3º leilão',  items: dados.value.terceiro     || [] },
  { key: 'quarto',      titulo: '4º leilão',  items: dados.value.quarto       || [] },
  { key: 'quinto_mais', titulo: '5+ leilões', items: dados.value.quinto_mais  || [] },
])

const precoDescendenteVisiveis = computed(() =>
  precoExpandido.value ? precoDescendente.value : precoDescendente.value.slice(0, PREVIEW)
)
</script>
