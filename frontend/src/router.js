import { createRouter, createWebHistory } from 'vue-router'
import LeiloesView from './views/LeiloesView.vue'
import LeilaoView  from './views/LeilaoView.vue'
import VeiculoView from './views/VeiculoView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',             component: LeiloesView },
    { path: '/leiloes/:id',  component: LeilaoView  },
    { path: '/veiculos/:id', component: VeiculoView },
  ],
})
