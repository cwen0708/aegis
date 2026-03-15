import { ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { config } from '../config'

const API = config.apiUrl

export interface ProjectInfo {
  id: number
  name: string
  path: string
  is_active: boolean
  is_system: boolean
}

// 全域單例狀態（跨元件共享）
const projects = ref<ProjectInfo[]>([])
const selectedProjectId = ref<number | null>(null)
const loaded = ref(false)

async function fetchProjects() {
  const res = await fetch(`${API}/api/v1/projects/`)
  if (res.ok) {
    const data = await res.json()
    let filtered = data.filter((p: any) => p.is_active)

    projects.value = filtered
  }
}

export function useProjectSelector() {
  const route = useRoute()
  const router = useRouter()

  const currentProject = () => projects.value.find(p => p.id === selectedProjectId.value)

  function selectProject(id: number) {
    selectedProjectId.value = id
    localStorage.setItem('aegis_selected_project', String(id))
    // 更新 URL query
    router.replace({ query: { ...route.query, project: String(id) } })
  }

  // 從 URL 或 localStorage 恢復
  function restoreSelection() {
    const fromUrl = route.query.project
    if (fromUrl) {
      const id = Number(fromUrl)
      if (projects.value.find(p => p.id === id)) {
        selectedProjectId.value = id
        return
      }
    }

    const fromStorage = localStorage.getItem('aegis_selected_project')
    if (fromStorage) {
      const id = Number(fromStorage)
      if (projects.value.find(p => p.id === id)) {
        selectedProjectId.value = id
        selectProject(id) // sync to URL
        return
      }
    }

    // 預設選第一個非系統專案
    const nonSystem = projects.value.find(p => !p.is_system)
    if (nonSystem) {
      selectProject(nonSystem.id)
    }
  }

  onMounted(async () => {
    if (!loaded.value) {
      await fetchProjects()
      loaded.value = true
    }
    restoreSelection()
  })

  // URL query 變化時同步
  watch(() => route.query.project, (val) => {
    if (val) {
      const id = Number(val)
      if (id !== selectedProjectId.value) {
        selectedProjectId.value = id
        localStorage.setItem('aegis_selected_project', String(id))
      }
    }
  })

  function selectAdjacentProject(direction: -1 | 1) {
    if (!projects.value.length) return
    const idx = projects.value.findIndex(p => p.id === selectedProjectId.value)
    const target = projects.value[idx + direction]
    if (target) {
      selectProject(target.id)
    }
  }

  return {
    projects,
    selectedProjectId,
    currentProject,
    selectProject,
    selectAdjacentProject,
    refreshProjects: fetchProjects,
  }
}
