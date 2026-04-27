import { createRouter, createWebHistory } from 'vue-router'
import LeiloesView  from './views/LeiloesView.vue'
import LeilaoView   from './views/LeilaoView.vue'
import VeiculoView  from './views/VeiculoView.vue'
import PesquisaView from './views/PesquisaView.vue'
import AnalisesView from './views/AnalisesView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',             component: LeiloesView  },
    { path: '/leiloes/:id',  component: LeilaoView   },
    { path: '/veiculos/:id', component: VeiculoView  },
    { path: '/pesquisa',     component: PesquisaView },
    { path: '/analises',     component: AnalisesView },
  ],
})
