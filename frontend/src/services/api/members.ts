import { apiClient } from './client'

// ── Types ──

export interface MemberAccount {
  account_id: number
  priority: number
  model: string
  name: string
  provider: string
  subscription: string
  is_healthy: boolean
}

export interface MemberInfo {
  id: number
  name: string
  avatar: string
  role: string
  description: string
  sprite_index: number
  portrait: string
  sprite_sheet: string
  sprite_scale: number
  provider: string
  accounts: MemberAccount[]
}

export interface AccountInfo {
  id: number
  provider: string
  name: string
  credential_file: string
  subscription: string
  email: string
  is_healthy: boolean
}

export interface SkillInfo {
  name: string
  title: string
  status: 'active' | 'draft'
}

// ── Members ──

export function listMembers(all = false) {
  const query = all ? '?all=true' : ''
  return apiClient.get<MemberInfo[]>(`/api/v1/members${query}`)
}

export function getMember(id: number) {
  return apiClient.get<MemberInfo>(`/api/v1/members/${id}`)
}

export function updateMember(id: number, data: Record<string, any>) {
  return apiClient.put(`/api/v1/members/${id}`, data)
}

export function deleteMember(id: number) {
  return apiClient.delete(`/api/v1/members/${id}`)
}

// ── Skills ──

export function listSkills(memberId: number) {
  return apiClient.get<SkillInfo[]>(`/api/v1/members/${memberId}/skills`)
}

export function getSkill(memberId: number, skillName: string) {
  return apiClient.get<{ content: string }>(`/api/v1/members/${memberId}/skills/${skillName}`)
}

export function createSkill(memberId: number, data: { name: string; content: string }) {
  return apiClient.post(`/api/v1/members/${memberId}/skills`, data)
}

export function updateSkill(memberId: number, skillName: string, data: { content: string }) {
  return apiClient.put(`/api/v1/members/${memberId}/skills/${skillName}`, data)
}

export function deleteSkill(memberId: number, skillName: string) {
  return apiClient.delete(`/api/v1/members/${memberId}/skills/${skillName}`)
}

export function approveSkill(memberId: number, skillName: string) {
  return apiClient.post(`/api/v1/members/${memberId}/skills/${skillName}/approve`)
}

// ── MCP ──

export function getMcpConfig(memberId: number) {
  return apiClient.get(`/api/v1/members/${memberId}/mcp`)
}

export function updateMcpConfig(memberId: number, rawJson: string) {
  return apiClient.putRaw(`/api/v1/members/${memberId}/mcp`, rawJson)
}

// ── Accounts ──

export function listAccounts() {
  return apiClient.get<AccountInfo[]>('/api/v1/accounts')
}

export function createAccount(memberId: number, data: { account_id: number; priority: number; model: string }) {
  return apiClient.post(`/api/v1/members/${memberId}/accounts`, data)
}

export function deleteAccount(memberId: number, accountId: number) {
  return apiClient.delete(`/api/v1/members/${memberId}/accounts/${accountId}`)
}

// ── Portrait ──

export function uploadPortrait(memberId: number, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.upload<{ portrait: string }>(`/api/v1/members/${memberId}/portrait`, formData)
}

export function generatePortrait(memberId: number, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.upload<{ portrait: string }>(`/api/v1/members/${memberId}/generate-portrait`, formData)
}
