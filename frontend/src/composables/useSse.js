import { onMounted, onUnmounted } from 'vue'

export function useSse(onNovoPreco) {
  let es = null

  function connect() {
    es = new EventSource('/api/events')

    es.addEventListener('novo_preco', (e) => {
      onNovoPreco(JSON.parse(e.data))
    })

    es.onerror = () => {
      es.close()
      setTimeout(connect, 5000)
    }
  }

  onMounted(connect)

  onUnmounted(() => {
    es?.close()
  })
}
