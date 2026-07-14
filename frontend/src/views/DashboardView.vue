<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '../stores/project'

const store = useProjectStore()
const router = useRouter()
const dialogVisible = ref(false)
const newProject = ref({ name: '', description: '' })
const creating = ref(false)

onMounted(() => store.fetchProjects())

async function handleCreate() {
  creating.value = true
  try {
    await store.createProject(newProject.value.name, newProject.value.description)
    dialogVisible.value = false
    newProject.value = { name: '', description: '' }
  } finally {
    creating.value = false
  }
}

function goProject(p: any) {
  store.setCurrentProject(p)
  router.push('/files')
}
</script>

<template>
  <div class="page-root">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h1 class="page-title">项目看板</h1>
        <p class="page-desc">管理你的项目和 Agent 工作区</p>
      </div>
      <button class="btn-primary" @click="dialogVisible = true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        创建项目
      </button>
    </div>

    <!-- Stats -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-value">{{ store.projects.length }}</div>
        <div class="stat-label">项目数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">0</div>
        <div class="stat-label">活跃 Agent</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">0</div>
        <div class="stat-label">待审查</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">—</div>
        <div class="stat-label">通过率</div>
      </div>
    </div>

    <!-- Project Grid -->
    <div v-if="store.projects.length > 0" class="project-grid">
      <article
        v-for="p in store.projects"
        :key="p.id"
        class="project-card"
        @click="goProject(p)"
      >
        <div class="project-card-icon">📁</div>
        <div class="project-card-body">
          <h3 class="project-card-title">{{ p.name }}</h3>
          <p class="project-card-desc">{{ p.description || '暂无描述' }}</p>
        </div>
        <svg class="project-card-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
      </article>
    </div>

    <!-- Empty -->
    <div v-else class="empty-card">
      <div class="empty-icon">📋</div>
      <h3>还没有项目</h3>
      <p>创建你的第一个项目，开始使用 Agent 协作审查</p>
      <button class="btn-secondary" @click="dialogVisible = true">创建第一个项目</button>
    </div>

    <!-- Dialog -->
    <el-dialog v-model="dialogVisible" title="创建项目" width="460px">
      <div class="dialog-form">
        <label class="field-label">项目名称</label>
        <input v-model="newProject.name" class="field-input" placeholder="例如：电商后台" />
        <label class="field-label">描述（选填）</label>
        <textarea v-model="newProject.description" class="field-textarea" rows="3" placeholder="简单描述项目用途" />
      </div>
      <template #footer>
        <button class="btn-ghost" @click="dialogVisible = false">取消</button>
        <button class="btn-primary" :disabled="!newProject.name || creating" @click="handleCreate">
          {{ creating ? '创建中...' : '创建' }}
        </button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-root { max-width: 1000px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 28px; }
.page-title { font-size: 22px; font-weight: 700; margin: 0; letter-spacing: -0.4px; }
.page-desc { font-size: 13.5px; color: var(--muted-foreground); margin: 4px 0 0; }

/* ── Buttons ────────────────────────────────────────────────────── */
.btn-primary {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: var(--radius-md);
  background: var(--primary); color: var(--primary-foreground);
  border: none; font-size: 13.5px; font-weight: 600; cursor: pointer;
  transition: opacity 0.15s;
}
.btn-primary:hover { opacity: 0.85; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }

.btn-secondary {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: var(--radius-md);
  background: var(--surface); color: var(--foreground);
  border: 1px solid var(--surface-border); font-size: 13.5px; font-weight: 600; cursor: pointer;
  transition: background 0.15s;
}
.btn-secondary:hover { background: var(--surface-hover); }

.btn-ghost {
  padding: 8px 16px; border-radius: var(--radius-md);
  background: transparent; color: var(--muted-foreground);
  border: none; font-size: 13.5px; font-weight: 500; cursor: pointer;
}
.btn-ghost:hover { background: var(--surface-hover); color: var(--foreground); }

/* ── Stat cards ─────────────────────────────────────────────────── */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
.stat-card {
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); padding: 18px 20px;
  box-shadow: var(--shadow-surface);
}
.stat-value { font-size: 26px; font-weight: 700; color: var(--foreground); letter-spacing: -0.5px; }
.stat-label { font-size: 12.5px; color: var(--muted-foreground); margin-top: 4px; }

/* ── Project grid ───────────────────────────────────────────────── */
.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.project-card {
  display: flex; align-items: center; gap: 14px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); padding: 16px 18px;
  box-shadow: var(--shadow-surface); cursor: pointer;
  transition: all 0.15s;
}
.project-card:hover { border-color: var(--ring); box-shadow: var(--shadow-floating); }
.project-card-icon { font-size: 24px; flex-shrink: 0; }
.project-card-body { flex: 1; min-width: 0; }
.project-card-title { font-size: 14px; font-weight: 600; margin: 0; color: var(--foreground); }
.project-card-desc { font-size: 12px; color: var(--muted-foreground); margin: 2px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-card-arrow { color: var(--muted-foreground); opacity: 0; transition: all 0.15s; flex-shrink: 0; }
.project-card:hover .project-card-arrow { opacity: 1; }

/* ── Empty state ────────────────────────────────────────────────── */
.empty-card {
  text-align: center; padding: 64px 32px;
  background: var(--surface); border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-surface);
}
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-card h3 { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
.empty-card p { font-size: 13px; color: var(--muted-foreground); margin: 0 0 20px; }

/* ── Dialog form ────────────────────────────────────────────────── */
.dialog-form { display: flex; flex-direction: column; gap: 8px; }
.field-label { font-size: 13px; font-weight: 600; color: var(--foreground); }
.field-input, .field-textarea {
  width: 100%; padding: 8px 12px; border: 1px solid var(--input);
  border-radius: var(--radius-md); font-size: 13.5px;
  font-family: var(--font-sans); color: var(--foreground);
  background: var(--surface); outline: none; box-sizing: border-box;
  transition: border-color 0.15s;
}
.field-input:focus, .field-textarea:focus { border-color: var(--ring); }
.field-textarea { resize: vertical; }
</style>
