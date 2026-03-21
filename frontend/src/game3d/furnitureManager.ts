import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import type { DeskPosition3D } from './types'
import { FURNITURE } from './types'

const loader = new GLTFLoader()

export function createFurnitureManager(scene: THREE.Scene) {
  const objects: THREE.Object3D[] = []

  async function loadFurniture(url: string, pos: THREE.Vector3, rotY = 0, scale = 1): Promise<THREE.Group> {
    const gltf = await loader.loadAsync(url)
    const model = gltf.scene
    model.position.copy(pos)
    model.rotation.y = rotY
    model.scale.setScalar(scale)
    model.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        child.castShadow = true
        child.receiveShadow = true
      }
    })
    scene.add(model)
    objects.push(model)
    return model
  }

  async function buildOffice(deskCount: number): Promise<DeskPosition3D[]> {
    const desks: DeskPosition3D[] = []
    const spacing = 4.0
    const rows = 2
    const cols = Math.ceil(deskCount / rows)
    const offsetX = -(cols - 1) * spacing / 2
    const rowGap = 5.0

    for (let i = 0; i < deskCount; i++) {
      const col = Math.floor(i / rows)
      const row = i % rows
      const x = offsetX + col * spacing
      const z = -rowGap / 2 + row * rowGap
      const rotY = row === 0 ? 0 : Math.PI

      // Desk
      await loadFurniture(FURNITURE.desk, new THREE.Vector3(x, 0, z), 0, 1)
      // Chair (behind desk)
      const chairZ = row === 0 ? z + 0.8 : z - 0.8
      await loadFurniture(FURNITURE.chairA, new THREE.Vector3(x, 0, chairZ), rotY, 1)

      desks.push({
        position: new THREE.Vector3(x, 0, chairZ),
        rotation: rotY,
        occupied: false,
      })
    }

    // Decorations — spread around the office
    await loadFurniture(FURNITURE.couch, new THREE.Vector3(-10, 0, 0), Math.PI / 2, 1)
    await loadFurniture(FURNITURE.couch, new THREE.Vector3(10, 0, 0), -Math.PI / 2, 1)
    await loadFurniture(FURNITURE.lamp, new THREE.Vector3(-10, 0, 3), 0, 1)
    await loadFurniture(FURNITURE.lamp, new THREE.Vector3(10, 0, -3), 0, 1)
    await loadFurniture(FURNITURE.cabinet, new THREE.Vector3(-8, 0, -8), 0, 1)
    await loadFurniture(FURNITURE.cabinet, new THREE.Vector3(8, 0, 8), Math.PI, 1)
    await loadFurniture(FURNITURE.cactus, new THREE.Vector3(12, 0, 5), 0, 1.2)
    await loadFurniture(FURNITURE.cactus, new THREE.Vector3(-12, 0, -5), 0, 1.2)
    await loadFurniture(FURNITURE.bookSet, new THREE.Vector3(0, 0, -8), 0, 1)

    return desks
  }

  function dispose() {
    for (const obj of objects) {
      scene.remove(obj)
      obj.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
          const mesh = child as THREE.Mesh
          mesh.geometry.dispose()
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
          mats.forEach(m => m.dispose())
        }
      })
    }
    objects.length = 0
  }

  return { buildOffice, dispose }
}

export type FurnitureManager = ReturnType<typeof createFurnitureManager>
