import { ref, computed } from 'vue'

export type UserRole = 'operator' | 'supervisor' | 'admin'

const roleLabels: Record<UserRole, string> = {
  operator: '客服专员',
  supervisor: '主管',
  admin: '管理员',
}

export function useCurrentUser() {
  const currentRole = ref<UserRole>((localStorage.getItem('kb_user_role') as UserRole) || 'supervisor')
  const currentUser = ref(localStorage.getItem('kb_user_name') || 'admin')

  const roleLabel = computed(() => roleLabels[currentRole.value] || currentRole.value)

  const isOperator = computed(() => currentRole.value === 'operator')
  const isSupervisor = computed(() => currentRole.value === 'supervisor' || currentRole.value === 'admin')
  const isAdmin = computed(() => currentRole.value === 'admin')
  const canEdit = computed(() => isSupervisor.value)
  const canAudit = computed(() => isSupervisor.value)

  function setRole(role: UserRole) {
    currentRole.value = role
    localStorage.setItem('kb_user_role', role)
  }

  function setUser(name: string) {
    currentUser.value = name
    localStorage.setItem('kb_user_name', name)
  }

  return {
    currentRole,
    currentUser,
    roleLabel,
    isOperator,
    isSupervisor,
    isAdmin,
    canEdit,
    canAudit,
    setRole,
    setUser,
  }
}

export default useCurrentUser
