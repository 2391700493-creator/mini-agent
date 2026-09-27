<script setup lang="ts">
import type { ModuleDefinition } from '../router/modules'
import AppIcon from '../components/AppIcon.vue'
import PageHeader from '../components/PageHeader.vue'
import ConnectionStatus from '../components/ConnectionStatus.vue'
defineProps<{ module: ModuleDefinition }>()
</script>

<template>
  <div class="module-page overview-page">
    <PageHeader :title="module.title" :description="module.description" />

    <section class="welcome-layout" aria-labelledby="welcome-title">
      <div class="welcome-copy">
        <div class="eyebrow">MINI-AGENT <span aria-hidden="true">/</span> {{ module.title }}</div>
        <h2 id="welcome-title">{{ module.headline }}</h2>
        <p class="welcome-description">{{ module.introduction }}</p>
        <RouterLink :to="module.action" class="button button-primary welcome-action">{{ module.actionLabel }} <AppIcon name="arrow" /></RouterLink>
      </div>
      <aside class="stage-card" aria-label="当前可用能力">
        <div class="stage-topline"><span>当前可用</span><AppIcon name="model" /></div>
        <p class="stage-title">连接模型<br />开始构建</p>
        <div class="stage-divider" />
        <p class="stage-note">添加模型、配置调用参数，<br />测试与模型服务的真实连接。</p>
        <RouterLink to="/models" class="text-link">管理模型 <AppIcon name="arrow" /></RouterLink>
      </aside>
    </section>

    <section class="next-section" aria-labelledby="next-title">
      <div class="placeholder-card">
        <div class="placeholder-heading">
          <span class="subtle-tag">待开发</span>
          <h3 id="next-title">接下来，在这里</h3>
        </div>
        <div class="placeholder-copy">
          <h4>本模块将在后续阶段开发</h4>
          <p>{{ module.next }}</p>
          <div class="current-focus"><AppIcon name="info" /><p>{{ module.focus }}</p></div>
        </div>
      </div>
    </section>

    <footer class="page-footer">
      <span class="footer-note">MINI-AGENT</span>
      <ConnectionStatus />
    </footer>
  </div>
</template>
