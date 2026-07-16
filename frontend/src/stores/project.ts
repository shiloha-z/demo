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
  const filterBy = ref<string>('all')

  async function fetchProjects(sort?: string, filter?: string) {
    const s = sort || sortBy.value
    const f = filter ?? filterBy.value
    const { data } = await api.get<{ projects: Project[] }>('/projects', { params: { sort: s, filter: f } })
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

  return { currentProject, projects, sortBy, filterBy, fetchProjects, createProject, setCurrentProject }
})
