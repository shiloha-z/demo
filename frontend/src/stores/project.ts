import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useProjectStore = defineStore('project', () => {
  const currentProject = ref<any>(null)
  const projects = ref<any[]>([])

  function setCurrentProject(project: any) {
    currentProject.value = project
  }

  return { currentProject, projects, setCurrentProject }
})
