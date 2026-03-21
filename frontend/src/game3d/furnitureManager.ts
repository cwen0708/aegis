import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import type { DeskPosition3D } from './types'
import { FURNITURE } from './types'

const loader = new GLTFLoader()

export function createFurnitureManager(scene: THREE.Scene) {
  const objects: THREE.Object3D[] = []

  function addObject(obj: THREE.Object3D) {
    scene.add(obj)
    objects.push(obj)
  }

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
    addObject(model)
    return model
  }

  // === Procedural geometry builders ===

  function createWall(x: number, z: number, w: number, h: number, d: number, rotY = 0, color = 0x2a2d4a) {
    const geo = new THREE.BoxGeometry(w, h, d)
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0.05 })
    const wall = new THREE.Mesh(geo, mat)
    wall.position.set(x, h / 2, z)
    wall.rotation.y = rotY
    wall.castShadow = true
    wall.receiveShadow = true
    addObject(wall)
    return wall
  }

  function createGlassPartition(x: number, z: number, w: number, h: number, rotY = 0) {
    // Frame
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x4a5568, roughness: 0.3, metalness: 0.6 })
    // Top bar
    const topGeo = new THREE.BoxGeometry(w, 0.04, 0.04)
    const top = new THREE.Mesh(topGeo, frameMat)
    top.position.set(x, h, z)
    top.rotation.y = rotY
    addObject(top)
    // Bottom bar
    const bot = new THREE.Mesh(topGeo, frameMat)
    bot.position.set(x, 0.4, z)
    bot.rotation.y = rotY
    addObject(bot)
    // Left post
    const postGeo = new THREE.BoxGeometry(0.04, h, 0.04)
    const offsetX = (w / 2) * Math.cos(rotY)
    const offsetZ = -(w / 2) * Math.sin(rotY)
    const leftPost = new THREE.Mesh(postGeo, frameMat)
    leftPost.position.set(x - offsetX, h / 2, z - offsetZ)
    addObject(leftPost)
    const rightPost = new THREE.Mesh(postGeo, frameMat)
    rightPost.position.set(x + offsetX, h / 2, z + offsetZ)
    addObject(rightPost)
    // Glass panel
    const glassGeo = new THREE.PlaneGeometry(w - 0.08, h - 0.44)
    const glassMat = new THREE.MeshPhysicalMaterial({
      color: 0x88aacc,
      transparent: true,
      opacity: 0.15,
      roughness: 0.05,
      metalness: 0.1,
      side: THREE.DoubleSide,
    })
    const glass = new THREE.Mesh(glassGeo, glassMat)
    glass.position.set(x, (h + 0.4) / 2, z)
    glass.rotation.y = rotY
    addObject(glass)
  }

  function createWhiteboard(x: number, z: number, w: number, h: number, rotY = 0) {
    // Board
    const boardGeo = new THREE.BoxGeometry(w, h, 0.05)
    const boardMat = new THREE.MeshStandardMaterial({ color: 0xf0f0f0, roughness: 0.3, metalness: 0.02 })
    const board = new THREE.Mesh(boardGeo, boardMat)
    board.position.set(x, 1.2 + h / 2, z)
    board.rotation.y = rotY
    board.castShadow = true
    addObject(board)
    // Frame
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x4a5568, roughness: 0.4, metalness: 0.5 })
    const frameGeo = new THREE.BoxGeometry(w + 0.06, h + 0.06, 0.03)
    const frame = new THREE.Mesh(frameGeo, frameMat)
    frame.position.set(x, 1.2 + h / 2, z + (rotY === 0 ? -0.04 : 0.04))
    frame.rotation.y = rotY
    addObject(frame)
  }

  function createPillar(x: number, z: number) {
    const geo = new THREE.CylinderGeometry(0.15, 0.15, 3, 8)
    const mat = new THREE.MeshStandardMaterial({ color: 0x3d4060, roughness: 0.4, metalness: 0.3 })
    const pillar = new THREE.Mesh(geo, mat)
    pillar.position.set(x, 1.5, z)
    pillar.castShadow = true
    addObject(pillar)
  }

  function createCeilingLight(x: number, z: number) {
    // Light fixture housing
    const housingGeo = new THREE.BoxGeometry(2.5, 0.06, 0.4)
    const housingMat = new THREE.MeshStandardMaterial({ color: 0x555878, roughness: 0.3, metalness: 0.4 })
    const housing = new THREE.Mesh(housingGeo, housingMat)
    housing.position.set(x, 3.2, z)
    addObject(housing)
    // Emissive strip
    const stripGeo = new THREE.PlaneGeometry(2.3, 0.3)
    const stripMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      emissive: 0xe8eaf0,
      emissiveIntensity: 0.6,
      side: THREE.DoubleSide,
    })
    const strip = new THREE.Mesh(stripGeo, stripMat)
    strip.position.set(x, 3.16, z)
    strip.rotation.x = Math.PI / 2
    addObject(strip)
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

      await loadFurniture(FURNITURE.desk, new THREE.Vector3(x, 0, z), 0, 1)
      const chairZ = row === 0 ? z + 0.8 : z - 0.8
      await loadFurniture(FURNITURE.chairA, new THREE.Vector3(x, 0, chairZ), rotY, 1)

      desks.push({
        position: new THREE.Vector3(x, 0, chairZ),
        rotation: rotY,
        occupied: false,
      })
    }

    // === Walls (back and sides) ===
    // Back wall
    createWall(0, -10, 30, 3.3, 0.2, 0, 0x252840)
    // Side walls
    createWall(-15, 0, 0.2, 3.3, 20, 0, 0x252840)
    createWall(15, 0, 0.2, 3.3, 20, 0, 0x252840)

    // === Glass partitions (meeting area dividers) ===
    createGlassPartition(-10, -3, 5, 2.0, 0)
    createGlassPartition(10, -3, 5, 2.0, 0)

    // === Whiteboards on back wall ===
    createWhiteboard(-5, -9.85, 3, 1.5, 0)
    createWhiteboard(5, -9.85, 3, 1.5, 0)

    // === Pillars ===
    createPillar(-8, -4)
    createPillar(8, -4)
    createPillar(-8, 4)
    createPillar(8, 4)

    // === Ceiling lights ===
    createCeilingLight(-4, -2)
    createCeilingLight(0, -2)
    createCeilingLight(4, -2)
    createCeilingLight(-4, 2)
    createCeilingLight(0, 2)
    createCeilingLight(4, 2)

    // === Furniture decorations ===
    // Lounge area (left)
    await loadFurniture(FURNITURE.couch, new THREE.Vector3(-12, 0, 0), Math.PI / 2, 1)
    await loadFurniture(FURNITURE.lamp, new THREE.Vector3(-12, 0, 2.5), 0, 1)
    await loadFurniture(FURNITURE.cactus, new THREE.Vector3(-13, 0, -2), 0, 1.2)

    // Lounge area (right)
    await loadFurniture(FURNITURE.couch, new THREE.Vector3(12, 0, 0), -Math.PI / 2, 1)
    await loadFurniture(FURNITURE.lamp, new THREE.Vector3(12, 0, -2.5), 0, 1)
    await loadFurniture(FURNITURE.cactus, new THREE.Vector3(13, 0, 2), 0, 1.2)

    // Back wall furniture
    await loadFurniture(FURNITURE.cabinet, new THREE.Vector3(-10, 0, -9), 0, 1)
    await loadFurniture(FURNITURE.cabinet, new THREE.Vector3(10, 0, -9), 0, 1)
    await loadFurniture(FURNITURE.bookSet, new THREE.Vector3(0, 0, -9), 0, 1)

    // Extra cactus near entrance
    await loadFurniture(FURNITURE.cactus, new THREE.Vector3(-3, 0, 8), 0, 1.5)
    await loadFurniture(FURNITURE.cactus, new THREE.Vector3(3, 0, 8), 0, 1.5)

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
