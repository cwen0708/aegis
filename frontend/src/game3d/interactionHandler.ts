import * as THREE from 'three'
import type { ActorManager } from './actorManager'
import type { CharacterClickInfo } from './types'

export function createInteractionHandler(
  camera: THREE.PerspectiveCamera,
  canvas: HTMLCanvasElement,
  actorManager: ActorManager,
  onCharacterClicked: (info: CharacterClickInfo) => void
) {
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()

  function onPointerDown(event: PointerEvent) {
    const rect = canvas.getBoundingClientRect()
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1

    raycaster.setFromCamera(pointer, camera)

    for (const actor of actorManager.actors.values()) {
      const intersects = raycaster.intersectObject(actor.model, true)
      if (intersects.length > 0) {
        onCharacterClicked({
          memberId: actor.memberId,
          name: actor.name,
          provider: actor.provider,
        })
        return
      }
    }
  }

  canvas.addEventListener('pointerdown', onPointerDown)

  function dispose() {
    canvas.removeEventListener('pointerdown', onPointerDown)
  }

  return { dispose }
}
