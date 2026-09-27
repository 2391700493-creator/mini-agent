import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { createAppRouter } from './router'
import './styles/tokens.css'
import './styles/main.css'
import './styles/evaluations.css'
import './styles/workspace.css'
import './styles/product.css'
import './styles/motion.css'

const router = createAppRouter()
const app = createApp(App).use(createPinia()).use(router)

// 首次路由就绪后再挂载，避免初始导航抢占键盘焦点。
void router.isReady().then(() => app.mount('#app'))
