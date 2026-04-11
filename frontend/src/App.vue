<template>
  <div class="min-h-screen bg-slate-50">

    <!-- Navbar -->
    <nav class="bg-white border-b border-slate-200 sticky top-0 z-50">
      <div class="max-w-7xl mx-auto px-10 h-14 flex items-center gap-4">
        <router-link
          to="/"
          class="flex items-center gap-2 text-slate-900 hover:text-blue-600 font-semibold no-underline shrink-0 transition-colors"
        >
          <i class="pi pi-car text-blue-600" />
          Everest
        </router-link>

        <div class="w-px h-5 bg-slate-200 mx-1" />

        <div class="flex gap-2 ml-auto w-72">
          <IconField class="flex-1">
            <InputIcon class="pi pi-search" />
            <InputText
              v-model="matricula"
              placeholder="Matrícula ou ID da viatura..."
              class="w-full"
              @keydown.enter="pesquisar"
            />
          </IconField>
          <Button icon="pi pi-search" :loading="loading" @click="pesquisar" />
        </div>

        <Message v-if="erro" severity="error" size="small" class="m-0 ml-2">{{ erro }}</Message>
      </div>
    </nav>

    <!-- Conteúdo principal -->
    <div class="max-w-7xl mx-auto px-10 py-8">
      <router-view />
    </div>

  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import InputText from 'primevue/inputtext'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import Button from 'primevue/button'
import Message from 'primevue/message'

const router    = useRouter()
const matricula = ref('')
const loading   = ref(false)
const erro      = ref('')

// lot_id são números com 7+ dígitos; matrícula tem letras e hífens
function isLotId(q) {
  return /^\d{5,}$/.test(q)
}

async function pesquisar() {
  const q = matricula.value.trim()
  if (!q) return

  loading.value = true
  erro.value    = ''

  const param = isLotId(q) ? `lot_id=${encodeURIComponent(q)}` : `matricula=${encodeURIComponent(q)}`
  const res        = await fetch(`/api/pesquisa?${param}`)
  const resultados = await res.json()

  loading.value = false

  if (!resultados.length) {
    erro.value = `"${q.toUpperCase()}" não encontrado.`
    setTimeout(() => { erro.value = '' }, 3000)
    return
  }

  matricula.value = ''
  router.push(`/veiculos/${resultados[0].veiculo.veiculo_id}`)
}
</script>
