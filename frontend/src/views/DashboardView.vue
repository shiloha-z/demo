<script setup lang="ts">
</script>

<template>
  <div class="page-container">
    <h2 class="page-title">📊 项目看板</h2>
    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="项目数" :value="0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="Agent 数" :value="0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="任务数" :value="0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="审查通过率" :value="0" suffix="%" />
        </el-card>
      </el-col>
    </el-row>
    <el-card class="section-card">
      <template #header>最近活动</template>
      <el-empty description="暂无数据" />
    </el-card>
  </div>
</template>

<style scoped>
.page-container { max-width: 1200px; }
.page-title { margin-bottom: 24px; font-size: 22px; }
.stat-row { margin-bottom: 24px; }
.section-card { min-height: 300px; }
</style>
