import type * as THREE from 'three'

export type MemberState = 'busy' | 'idle'

export interface Actor3D {
  memberId: number
  name: string
  provider: string
  state: MemberState
  model: THREE.Group
  mixer: THREE.AnimationMixer
  actions: Map<string, THREE.AnimationAction>
  currentAction: string
  targetPosition: THREE.Vector3 | null
  roamTimer: number
  labelDiv: HTMLDivElement
}

export interface DeskPosition3D {
  position: THREE.Vector3
  rotation: number // Y-axis rotation for chair facing
  occupied: boolean
}

export interface SceneData3D {
  desks: Array<{ memberId: number; name: string; provider: string; deskIndex: number }>
  resting: Array<{ memberId: number; name: string; provider: string }>
  bubbles: Map<number, string>
}

export interface CharacterClickInfo {
  memberId: number
  name: string
  provider: string
}

// KayKit character model paths
export const CHARACTER_MODELS = [
  '/assets/3d/characters/Barbarian.glb',
  '/assets/3d/characters/Knight.glb',
  '/assets/3d/characters/Mage.glb',
  '/assets/3d/characters/Rogue.glb',
  '/assets/3d/characters/Rogue_Hooded.glb',
]

// Furniture paths
export const FURNITURE = {
  desk: '/assets/3d/furniture/table_medium.gltf',
  chairA: '/assets/3d/furniture/chair_A.gltf',
  chairB: '/assets/3d/furniture/chair_B.gltf',
  lamp: '/assets/3d/furniture/lamp_table.gltf',
  bookSet: '/assets/3d/furniture/book_set.gltf',
  cabinet: '/assets/3d/furniture/cabinet_small.gltf',
  cactus: '/assets/3d/furniture/cactus_small_A.gltf',
  couch: '/assets/3d/furniture/couch.gltf',
}
