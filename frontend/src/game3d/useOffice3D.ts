import { ref, onUnmounted, type Ref } from 'vue'
import { createScene } from './sceneSetup'
import { createActorManager } from './actorManager'
import { createFurnitureManager } from './furnitureManager'
import { createBehaviorController } from './behaviorController'
import { createInteractionHandler } from './interactionHandler'
import type { SceneData3D, CharacterClickInfo, DeskPosition3D } from './types'
import * as THREE from 'three'

export function useOffice3D(
  canvasRef: Ref<HTMLCanvasElement | null>,
  labelContainerRef: Ref<HTMLDivElement | null>,
  options: {
    onCharacterClicked: (info: CharacterClickInfo) => void
  }
) {
  const isLoading = ref(true)
  let disposed = false
  let animFrameId = 0

  // Scene modules (initialized in init())
  let sceneCtx: ReturnType<typeof createScene> | null = null
  let actorMgr: ReturnType<typeof createActorManager> | null = null
  let furnitureMgr: ReturnType<typeof createFurnitureManager> | null = null
  let behaviorCtrl: ReturnType<typeof createBehaviorController> | null = null
  let interactionHandler: ReturnType<typeof createInteractionHandler> | null = null
  let desks: DeskPosition3D[] = []

  // Track which members are currently displayed
  const currentMembers = new Set<number>()

  async function init() {
    const canvas = canvasRef.value
    const labelContainer = labelContainerRef.value
    if (!canvas || !labelContainer) return

    sceneCtx = createScene(canvas, labelContainer)
    actorMgr = createActorManager(sceneCtx.scene)
    furnitureMgr = createFurnitureManager(sceneCtx.scene)

    // Build office with 6 desks by default
    try {
      desks = await furnitureMgr.buildOffice(6)
    } catch (e) {
      console.warn('[3D] Failed to load furniture, using empty office:', e)
      desks = []
    }

    const bounds = { minX: -5, maxX: 5, minZ: -4, maxZ: 4 }
    behaviorCtrl = createBehaviorController(actorMgr, desks, bounds)

    interactionHandler = createInteractionHandler(
      sceneCtx.camera,
      canvas,
      actorMgr,
      options.onCharacterClicked
    )

    isLoading.value = false

    // Render loop
    const loop = () => {
      if (disposed) return
      animFrameId = requestAnimationFrame(loop)

      const delta = sceneCtx!.clock.getDelta()
      sceneCtx!.controls.update()
      actorMgr!.update(delta)
      behaviorCtrl!.update(delta)
      sceneCtx!.renderer.render(sceneCtx!.scene, sceneCtx!.camera)
      sceneCtx!.labelRenderer.render(sceneCtx!.scene, sceneCtx!.camera)
    }
    loop()
  }

  async function updateData(data: SceneData3D) {
    if (!actorMgr || !behaviorCtrl) return

    const newMemberIds = new Set<number>()

    // Process busy members (at desks)
    for (const desk of data.desks) {
      newMemberIds.add(desk.memberId)
      const existing = actorMgr.actors.get(desk.memberId)
      if (!existing) {
        const deskPos = desks[desk.deskIndex]
        const spawnPos = deskPos ? deskPos.position.clone().add(new THREE.Vector3(0, 0, 1)) : new THREE.Vector3(Math.random() * 4 - 2, 0, Math.random() * 4 - 2)
        try {
          await actorMgr.addActor(desk.memberId, desk.name, desk.provider, spawnPos, 'busy')
          behaviorCtrl.assignBusy(desk.memberId, desk.deskIndex)
        } catch (e) {
          console.warn(`[3D] Failed to add actor ${desk.name}:`, e)
        }
      } else if (existing.state !== 'busy') {
        existing.state = 'busy'
        behaviorCtrl.assignBusy(desk.memberId, desk.deskIndex)
      }
    }

    // Process idle members (roaming)
    for (const rest of data.resting) {
      newMemberIds.add(rest.memberId)
      const existing = actorMgr.actors.get(rest.memberId)
      if (!existing) {
        const pos = new THREE.Vector3(Math.random() * 6 - 3, 0, Math.random() * 6 - 3)
        try {
          await actorMgr.addActor(rest.memberId, rest.name, rest.provider, pos, 'idle')
          behaviorCtrl.assignIdle(rest.memberId)
        } catch (e) {
          console.warn(`[3D] Failed to add actor ${rest.name}:`, e)
        }
      } else if (existing.state !== 'idle') {
        existing.state = 'idle'
        behaviorCtrl.assignIdle(rest.memberId)
      }
    }

    // Remove actors no longer present
    for (const id of currentMembers) {
      if (!newMemberIds.has(id)) {
        actorMgr.removeActor(id)
      }
    }
    currentMembers.clear()
    for (const id of newMemberIds) {
      currentMembers.add(id)
    }
  }

  function dispose() {
    disposed = true
    cancelAnimationFrame(animFrameId)
    interactionHandler?.dispose()
    actorMgr?.dispose()
    furnitureMgr?.dispose()
    sceneCtx?.dispose()
  }

  onUnmounted(dispose)

  return { init, updateData, isLoading, dispose }
}
