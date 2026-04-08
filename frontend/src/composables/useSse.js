import { onMounted, onUnmounted } from 'vue'

export function useSse(onNovoPreco) {
  let es = null

  onMounted(() => {
    es = new EventSource('/api/events')

    es.addEventListener('novo_preco', (e) => {
      onNovoPreco(JSON.parse(e.data))
    })

    es.onerror = () => {
      // Reconectar automaticamente após 5s
      setTimeout(() => {
        es.close()
        es = new EventSource('/api/events')
      }, 5000)
    }
  })

  onUnmounted(() => {
    es?.close()
  })
}
