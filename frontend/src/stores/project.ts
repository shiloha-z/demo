import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export interface Project {
  id: number
  project_id: string | null
  name: string
  description: string
  owner_id: number
  owner_name: string
  workspace_path: string
  is_member: boolean
  created_at: string | null
  updated_at: string | null
}

export const useProjectStore = defineStore('project', () => {
  const currentProject = ref<Project | null>(null)
  const projects = ref<Project[]>([])
  // Separate from the dashboard list: this is the only source for the global
  // project switcher and contains projects the current user can access.
  const switchableProjects = ref<Project[]>([])
  const sortBy = ref<string>('created_desc')
  const filterBy = ref<string>('all')

  async function fetchProjects(sort?: string, filter?: string) {
    const s = sort || sortBy.value
    const f = filter ?? filterBy.value
    const { data } = await api.get<{ projects: Project[] }>('/projects', { params: { sort: s, filter: f } })
    projects.value = data.projects
  }

  async function fetchSwitchableProjects() {
    const { data } = await api.get<{ projects: Project[] }>('/projects', {
      params: { sort: sortBy.value, filter: 'joined' },
    })
    switchableProjects.value = data.projects
  }

  async function createProject(name: string, description: string, workspace_name?: string): Promise<Project> {
    const { data } = await api.post<Project>('/projects', { name, description, workspace_name })
    projects.value.unshift(data)
    switchableProjects.value.unshift(data)
    return data
  }

  function setCurrentProject(project: Project | null): boolean {
    if (!project) {
      currentProject.value = null
      return true
    }
    const allowed = switchableProjects.value.find(p => p.id === project.id)
    currentProject.value = allowed || null
    return !!allowed
  }

  return {
    currentProject, projects, switchableProjects, sortBy, filterBy,
    fetchProjects, fetchSwitchableProjects, createProject, setCurrentProject,
  }
})
