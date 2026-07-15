import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export interface Project {
  id: number
  name: string
  description: string
  owner_id: number
  owner_name: string
  workspace_path: string
  created_at: string | null
  updated_at: string | null
}

export const useProjectStore = defineStore('project', () => {
  const currentProject = ref<Project | null>(null)
  const projects = ref<Project[]>([])
  const sortBy = ref<string>('created_desc')

  async function fetchProjects(sort?: string) {
    const s = sort || sortBy.value
    const { data } = await api.get<{ projects: Project[] }>('/projects', { params: { sort: s } })
    projects.value = data.projects
  }

  async function createProject(name: string, description: string, workspace_name?: string): Promise<Project> {
    const { data } = await api.post<Project>('/projects', { name, description, workspace_name })
    projects.value.unshift(data)
    return data
  }

  function setCurrentProject(project: Project | null) {
    currentProject.value = project
  }

  return { currentProject, projects, sortBy, fetchProjects, createProject, setCurrentProject }
})
