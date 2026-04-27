<template>
  <div v-if="items.length > 0">

    <div class="flex items-center gap-3 mb-3">
      <h2 class="text-base font-semibold text-slate-700">{{ titulo }}</h2>
      <span class="text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
        {{ items.length }} viaturas
      </span>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-2">
      <div
        v-for="v in visíveis"
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
          <span class="absolute top-1 right-1 bg-blue-600 text-white font-semibold px-1.5 py-0.5 rounded-full" style="font-size:0.6rem">
            {{ v.num_leiloes }}x
          </span>
        </div>
        <div class="p-1.5">
          <p class="font-semibold text-slate-800 leading-snug truncate" style="font-size:0.65rem">{{ v.marca_modelo }}</p>
          <p v-if="v.matricula" class="text-blue-500 truncate" style="font-size:0.6rem">{{ v.matricula }}</p>
          <p class="text-slate-400 truncate" style="font-size:0.6rem">
            <span v-if="v.ano_construcao && v.ano_construcao !== '0'">{{ v.ano_construcao }} · </span>
            <span v-if="v.km">{{ Number(v.km).toLocaleString('pt-PT') }} km</span>
          </p>
        </div>
      </div>
    </div>

    <button
      v-if="items.length > PREVIEW"
      class="mt-2 text-xs text-blue-600 hover:underline"
      @click="expandido = !expandido"
    >
      {{ expandido ? 'Recolher' : `Ver todos (${items.length})` }}
    </button>

  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  titulo: String,
  items:  { type: Array, default: () => [] },
})

const router    = useRouter()
const expandido = ref(false)
const PREVIEW   = 5

const visíveis = computed(() => expandido.value ? props.items : props.items.slice(0, PREVIEW))
</script>
