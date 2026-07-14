import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export interface Project {
  id: number
  name: string
  description: string
  owner_id: number
  workspace_path: string
}

export const useProjectStore = defineStore('project', () => {
  const currentProject = ref<Project | null>(null)
  const projects = ref<Project[]>([])

  async function fetchProjects() {
    const { data } = await api.get<{ projects: Project[] }>('/projects')
    projects.value = data.projects
  }

  async function createProject(name: string, description: string): Promise<Project> {
    const { data } = await api.post<Project>('/projects', { name, description })
    projects.value.unshift(data)
    return data
  }

  function setCurrentProject(project: Project | null) {
    currentProject.value = project
  }

  return { currentProject, projects, fetchProjects, createProject, setCurrentProject }
})
